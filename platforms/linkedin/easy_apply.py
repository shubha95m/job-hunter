import asyncio
import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import Locator, Page

from llm_wrapper import generate_action

load_dotenv()


MODAL_SELECTOR = (
    "dialog[open], "
    "dialog[data-testid='dialog'], "
    "[data-testid='dialog'], "
    ".jobs-easy-apply-modal, "
    ".artdeco-modal:not([data-testid*='popover']), "
    "[role='dialog']:not([data-testid*='popover'])"
)


SYSTEM_PROMPT = """You are helping fill a LinkedIn Easy Apply form.

You will receive structured DOM data from the visible Easy Apply modal:
- fields: visible input/select/textarea controls with stable ids/selectors, labels, values, options, required state, and validation errors
- buttons: visible modal buttons
- profile: the applicant profile and standard answers

Return ONLY a JSON array of actions. No markdown.

Supported actions:
[
  {"action": "fill", "id": "field-id", "value": "answer"},
  {"action": "select", "id": "field-id", "value": "Exact option text"},
  {"action": "check", "id": "field-id"},
  {"action": "upload", "id": "field-id", "path": "resume.pdf"},
  {"action": "click", "text": "Next"},
  {"action": "done"}
]

Rules:
1. Use the id from the field whenever it exists. If a field has no id, use its selector.
2. Fill all visible empty required fields and any field with a validation error.
3. Do not refill fields that already have a correct value.
4. Numeric fields must contain digits only: no commas, currency symbols, units, or words.
5. Years of experience must be a number only.
6. For dropdowns, use one of the provided option labels exactly.
7. For radio/checkbox questions, choose the option that best matches profile.standard_answers.
8. For file upload fields, use an upload action with profile.resume_path.
9. If a field has an error, fix that field before clicking the next button.
10. Always finish with one click action using one of the visible enabled buttons, unless the form is already submitted.
11. If a success/confirmation state is present, return [{"action": "done"}].
12. Never click Dismiss, Cancel, or Discard.
"""


async def get_easy_apply_modal(page: Page, timeout: int = 15000) -> Locator:
    locator = page.locator(MODAL_SELECTOR)
    try:
        await locator.first.wait_for(state="visible", timeout=timeout)
    except Exception:
        pass

    count = await locator.count()
    for i in range(count):
        candidate = locator.nth(i)
        if not await candidate.is_visible():
            continue
        test_id = (await candidate.get_attribute("data-testid") or "").lower()
        if "popover" in test_id:
            continue
        has_form_controls = await candidate.locator("input, select, textarea").count() > 0
        has_apply_buttons = await candidate.locator(
            "button:has-text('Submit'), button:has-text('Next'), button:has-text('Review'), "
            "button:has-text('Upload'), button:has-text('Dismiss'), button[aria-label='Dismiss']"
        ).count() > 0
        if has_form_controls or has_apply_buttons:
            return candidate

    for i in range(count):
        candidate = locator.nth(i)
        if await candidate.is_visible():
            return candidate

    return locator.first


async def is_submission_success(page: Page) -> bool:
    success_text = page.locator(
        "text=/application submitted|your application was sent|application sent|your application has been sent/i"
    )
    try:
        if await success_text.first.is_visible(timeout=1500):
            return True
    except Exception:
        pass

    post_apply = page.locator(
        "[data-testid='dialog']:has-text('Application submitted'), "
        "dialog[open]:has-text('Application submitted'), "
        "h2:has-text('Application submitted'), "
        "h3:has-text('Application submitted')"
    )
    try:
        if await post_apply.first.is_visible(timeout=1500):
            return True
    except Exception:
        pass

    return False


async def extract_form_context(page: Page) -> dict[str, Any]:
    modal = await get_easy_apply_modal(page)

    data = await modal.evaluate(
        """
        (root) => {
            const fieldSelector = 'input, select, textarea';
            const buttonSelector = 'button';

            function visible(el) {
                const type = (el.getAttribute('type') || '').toLowerCase();
                if (type === 'file' || type === 'radio' || type === 'checkbox') return true;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && rect.width > 0
                    && rect.height > 0;
            }

            function cssEscape(value) {
                if (window.CSS && CSS.escape) return CSS.escape(value);
                return String(value).replace(/["\\\\]/g, '\\\\$&');
            }

            function text(el) {
                return (el && el.innerText ? el.innerText : '').replace(/\\s+/g, ' ').trim();
            }

            function labelFor(el) {
                const ariaLabel = (el.getAttribute('aria-label') || '').trim();
                if (ariaLabel && !['dismiss', 'search', 'close'].includes(ariaLabel.toLowerCase())) {
                    return ariaLabel;
                }

                const labelledBy = el.getAttribute('aria-labelledby');
                if (labelledBy) {
                    const labelEl = root.querySelector(`[id="${cssEscape(labelledBy)}"]`) || document.getElementById(labelledBy);
                    if (labelEl && text(labelEl)) return text(labelEl);
                }

                const labels = Array.from(el.labels || []).map(text).filter(Boolean);
                const type = (el.getAttribute('type') || '').toLowerCase();

                if (type === 'radio' || type === 'checkbox') {
                    let optionText = labels.join(' / ');
                    if (!optionText && el.parentElement && el.parentElement.parentElement) {
                        optionText = text(el.parentElement.parentElement);
                    }
                    if (!optionText && el.parentElement) {
                        optionText = text(el.parentElement);
                    }

                    let groupQuestion = '';
                    let parent = el.parentElement;
                    while (parent && parent !== root) {
                        const q = parent.querySelector('legend, h3, h4, [class*="header"], [class*="title"]');
                        if (q && text(q) && text(q).length > 3) {
                            groupQuestion = text(q);
                            break;
                        }
                        const pTag = parent.querySelector('p, span');
                        if (pTag && text(pTag) && text(pTag).length > 3 && !['yes', 'no'].includes(text(pTag).toLowerCase())) {
                            groupQuestion = text(pTag);
                            break;
                        }
                        parent = parent.parentElement;
                    }
                    if (groupQuestion && optionText) return `${groupQuestion} - ${optionText}`;
                    return groupQuestion || optionText;
                }

                if (labels.length) return labels.join(' / ');

                if (el.id) {
                    const explicit = root.querySelector(`label[for="${cssEscape(el.id)}"]`);
                    if (explicit) return text(explicit);
                }

                let parent = el.parentElement;
                while (parent && parent !== root) {
                    const label = parent.querySelector('label');
                    if (label && text(label)) return text(label);
                    const spans = Array.from(parent.querySelectorAll('span, p, h3, h4'))
                        .map(text)
                        .filter(Boolean)
                        .filter(v => v.length > 2 && v.length < 200 && v !== el.value);
                    if (spans.length) return spans[0];
                    parent = parent.parentElement;
                }

                return '';
            }

            function errorFor(el) {
                const container = el.closest(
                    '.jobs-easy-apply-form-section__grouping, .fb-dash-form-element, fieldset, div'
                );
                if (!container) return '';
                const err = container.querySelector(
                    '.artdeco-inline-feedback--error, .fb-dash-form-element__error-text, [role="alert"]'
                );
                return text(err);
            }

            function selectorFor(el, index) {
                if (el.id) return `[id="${cssEscape(el.id)}"]`;
                if (el.name) return `${el.tagName.toLowerCase()}[name="${cssEscape(el.name)}"]`;
                el.setAttribute('data-agent-field-index', String(index));
                return `[data-agent-field-index="${index}"]`;
            }

            const fields = Array.from(root.querySelectorAll(fieldSelector))
                .filter(visible)
                .map((el, index) => {
                    const tag = el.tagName.toLowerCase();
                    const type = (el.getAttribute('type') || tag).toLowerCase();
                    const options = tag === 'select'
                        ? Array.from(el.options).map((o) => o.text.trim()).filter(Boolean)
                        : [];
                    return {
                        id: el.id || '',
                        selector: selectorFor(el, index),
                        tag,
                        type,
                        label: labelFor(el),
                        placeholder: el.getAttribute('placeholder') || '',
                        name: el.getAttribute('name') || '',
                        value: type === 'checkbox' || type === 'radio' ? (el.checked ? 'selected' : '') : el.value || '',
                        checked: Boolean(el.checked),
                        required: Boolean(el.required || el.getAttribute('aria-required') === 'true'),
                        disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
                        options,
                        error: errorFor(el)
                    };
                })
                .filter((field) => !field.disabled);

            const buttons = Array.from(root.querySelectorAll(buttonSelector))
                .filter(visible)
                .map((button) => ({
                    text: text(button) || button.getAttribute('aria-label') || '',
                    ariaLabel: button.getAttribute('aria-label') || '',
                    disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true')
                }))
                .filter((button) => button.text || button.ariaLabel);

            const errors = Array.from(root.querySelectorAll(
                '.artdeco-inline-feedback--error, .fb-dash-form-element__error-text, [role="alert"]'
            )).map(text).filter(Boolean);

            return { fields, buttons, errors, modalText: text(root).slice(0, 2500) };
        }
        """
    )

    return data


def compact_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "fields": context.get("fields", []),
        "buttons": [
            button for button in context.get("buttons", [])
            if not button.get("disabled")
        ],
        "errors": context.get("errors", []),
    }


def has_fields_needing_input(context: dict[str, Any]) -> bool:
    if context.get("errors"):
        return True

    radio_groups: dict[str, list[dict[str, Any]]] = {}

    for field in context.get("fields", []):
        field_type = str(field.get("type", "")).lower()
        tag = str(field.get("tag", "")).lower()
        if field_type in {"hidden", "submit", "button"}:
            continue
        if field_type == "radio":
            group_key = field.get("name") or field.get("label", "").split(" - ")[0]
            radio_groups.setdefault(group_key, []).append(field)
            continue
        if field_type == "checkbox" and field.get("required") and not field.get("checked"):
            return True
        if tag in {"input", "select", "textarea"} and field_type != "checkbox" and not field.get("value"):
            return True
        if field.get("required") and not field.get("value"):
            return True

    for group in radio_groups.values():
        any_checked = any(f.get("checked") for f in group)
        if not any_checked:
            return True

    return False


def primary_progression_action(context: dict[str, Any]) -> list[dict[str, Any]]:
    priority = [
        "Submit application",
        "Submit",
        "Review application",
        "Review your application",
        "Review",
        "Next",
        "Continue to next step",
        "Continue",
        "Done",
    ]
    enabled_buttons = [
        button for button in context.get("buttons", [])
        if not button.get("disabled")
    ]

    for wanted in priority:
        for button in enabled_buttons:
            text = (button.get("text") or button.get("ariaLabel") or "").strip()
            if text.lower() == wanted.lower():
                return [{"action": "click", "text": text}]

    return []


async def decide_next_actions(context: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    if not has_fields_needing_input(context):
        fallback = primary_progression_action(context)
        if fallback:
            return fallback

    prompt = f"""{SYSTEM_PROMPT}

PROFILE:
{json.dumps(profile, indent=2)}

FORM_CONTEXT:
{json.dumps(compact_context(context), indent=2)}
"""
    actions = await generate_action(prompt)
    return actions if isinstance(actions, list) else []


def css_id_selector(element_id: str) -> str:
    return f'[id="{element_id.replace(chr(92), chr(92) + chr(92)).replace(chr(34), chr(92) + chr(34))}"]'


async def resolve_field(modal: Locator, action: dict[str, Any]) -> Locator:
    if action.get("id"):
        return modal.locator(css_id_selector(str(action["id"]))).first
    if action.get("selector"):
        return modal.locator(str(action["selector"])).first
    if action.get("label"):
        return modal.get_by_label(str(action["label"])).first
    raise ValueError(f"Action has no field target: {action}")


async def click_modal_button(modal: Locator, text: str) -> None:
    normalized = text.strip()
    if not normalized:
        raise ValueError("Click action missing button text")

    button = modal.get_by_role("button", name=normalized, exact=True).first
    if await button.count() == 0:
        button = modal.get_by_role("button", name=re.compile(rf"^{re.escape(normalized)}$", re.IGNORECASE)).first
    if await button.count() == 0:
        button = modal.locator(f"button:has-text('{normalized}'), button[aria-label*='{normalized}' i]").first
    if await button.count() == 0:
        raise ValueError(f"Button not found in Easy Apply modal: {normalized}")

    try:
        await button.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass

    try:
        await button.click(timeout=10000)
    except Exception as exc:
        print(f"    Standard click failed ({exc}), attempting force click...")
        await button.click(force=True, timeout=5000)


async def select_option(field: Locator, value: str) -> None:
    try:
        await field.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        await field.select_option(label=value, timeout=5000)
        return
    except Exception:
        pass
    try:
        await field.select_option(value=value, timeout=5000)
        return
    except Exception:
        pass

    await field.click(timeout=5000)
    option = field.page.get_by_role("option", name=value, exact=True).first
    if await option.count() == 0:
        option = field.page.get_by_text(value, exact=True).first
    await option.click(timeout=5000)


async def execute_actions(page: Page, actions: list[dict[str, Any]], profile: dict[str, Any] = None) -> str:
    modal = await get_easy_apply_modal(page)
    field_failed = False
    clicked_submit = False
    clicked_progress = False

    for action in actions:
        action_type = str(action.get("action", "")).lower()

        if action_type == "done":
            return "submitted"

        if action_type == "click":
            if field_failed:
                print("  Skipping progression click because a field action failed.")
                return "field_error"
            button_text = str(action.get("text") or action.get("button") or "")
            print(f"  -> Clicking button [{button_text}]")
            await click_modal_button(modal, button_text)
            clicked_progress = True
            clicked_submit = "submit" in button_text.lower()
            await asyncio.sleep(1)
            continue

        try:
            field = await resolve_field(modal, action)
            value = str(action.get("value", ""))

            if action_type == "fill":
                print(f"  -> Filling [{action.get('id') or action.get('selector')}] with '{value}'")
                await field.scroll_into_view_if_needed(timeout=5000)
                await field.fill(value, timeout=10000)
            elif action_type == "select":
                print(f"  -> Selecting '{value}' in [{action.get('id') or action.get('selector')}]")
                await select_option(field, value)
            elif action_type == "check":
                print(f"  -> Checking [{action.get('id') or action.get('selector')}]")
                field_id = action.get("id")
                checked = False

                # 1. First try clicking the label associated with this input
                if field_id:
                    lbl = modal.locator(f'label[for="{field_id}"]').first
                    if await lbl.count() > 0:
                        try:
                            await lbl.scroll_into_view_if_needed(timeout=3000)
                            await lbl.click(timeout=3000)
                            checked = True
                        except Exception:
                            pass

                # 2. Try clicking closest parent label or evaluating DOM click + change
                if not checked:
                    try:
                        res = await field.evaluate("""el => {
                            const id = el.id;
                            if (id) {
                                const l = document.querySelector(`label[for="${id}"]`);
                                if (l) { l.click(); return true; }
                            }
                            const parentLabel = el.closest('label');
                            if (parentLabel) { parentLabel.click(); return true; }
                            el.checked = true;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }""")
                        if res:
                            checked = True
                    except Exception:
                        pass

                # 3. Standard Playwright check/click fallback
                if not checked:
                    try:
                        await field.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    try:
                        await field.check(timeout=3000)
                    except Exception:
                        await field.click(force=True, timeout=3000)
            elif action_type == "upload":
                file_path = str(action.get("path") or action.get("value") or "")
                if not file_path and profile and profile.get("resume_path"):
                    file_path = profile["resume_path"]
                abs_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
                print(f"  -> Uploading file '{abs_path}' to [{action.get('id') or action.get('selector')}]")
                try:
                    await field.set_input_files(abs_path, timeout=5000)
                except Exception:
                    file_input = modal.locator("input[type='file']").first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(abs_path, timeout=5000)
                    else:
                        raise
            else:
                print(f"  ? Unknown action type: {action_type}")
        except Exception as exc:
            field_failed = True
            print(f"  ! Field action failed: {action} | {exc}")

    if clicked_submit:
        return "submitted"
    if clicked_progress:
        return "progressed"
    return "no_progress"


def state_signature(context: dict[str, Any]) -> str:
    signature = {
        "fields": [
            {
                "id": field.get("id"),
                "selector": field.get("selector"),
                "value": field.get("value"),
                "error": field.get("error"),
            }
            for field in context.get("fields", [])
        ],
        "buttons": context.get("buttons", []),
        "errors": context.get("errors", []),
    }
    return json.dumps(signature, sort_keys=True)


async def execute_smart_form_fill(page: Page, profile: dict[str, Any]) -> bool:
    print("\n--- Starting DOM Form Filling ---")
    max_steps = 18
    unchanged_steps = 0
    previous_signature = ""

    for step in range(max_steps):
        print(f"\nStep {step + 1}: Reading Easy Apply modal DOM...")

        # Give modal content and buttons a moment to render/settle
        await asyncio.sleep(1.2)

        if await is_submission_success(page):
            done_btn = page.locator("button:has-text('Done'), [data-testid='dialog'] button:has-text('Done')").first
            if await done_btn.count() > 0 and await done_btn.is_visible():
                try:
                    await done_btn.click(timeout=3000)
                except Exception:
                    pass
            print("  Application submitted successfully.")
            return True

        try:
            context = await extract_form_context(page)
        except Exception as exc:
            if await is_submission_success(page):
                print("  Application submitted successfully.")
                return True
            print(f"  Could not read Easy Apply modal: {exc}")
            return False

        current_signature = state_signature(context)
        if current_signature == previous_signature:
            unchanged_steps += 1
        else:
            unchanged_steps = 0
        previous_signature = current_signature

        if unchanged_steps >= 3:
            print("  Form state did not change after multiple attempts. Stopping this job.")
            return False

        if context.get("errors"):
            print(f"  Validation errors: {' | '.join(context['errors'])}")

        actions = await decide_next_actions(context, profile)
        if not actions:
            print("  AI returned no valid actions.")
            return False

        print(f"  AI returned {len(actions)} action(s): {actions}")
        if any(action.get("action") == "done" for action in actions):
            if await is_submission_success(page):
                done_btn = page.locator("button:has-text('Done'), [data-testid='dialog'] button:has-text('Done')").first
                if await done_btn.count() > 0 and await done_btn.is_visible():
                    try:
                        await done_btn.click(timeout=3000)
                    except Exception:
                        pass
                print("  Application submitted successfully.")
                return True
            # AI prematurely returned done while form is not yet submitted.
            progression = primary_progression_action(context)
            if progression:
                actions = progression
            else:
                return False

        try:
            result = await execute_actions(page, actions, profile)
        except Exception as exc:
            print(f"  Action execution failed: {exc}")
            return False

        if result == "submitted":
            await asyncio.sleep(2)
            if await is_submission_success(page):
                done_btn = page.locator("button:has-text('Done'), [data-testid='dialog'] button:has-text('Done')").first
                if await done_btn.count() > 0 and await done_btn.is_visible():
                    try:
                        await done_btn.click(timeout=3000)
                    except Exception:
                        pass
                print("  Application submitted successfully.")
                return True
            print("  Submit was clicked but no confirmation was detected yet.")

        await asyncio.sleep(1)

    print("--- Form filling reached max steps ---\n")
    return False
