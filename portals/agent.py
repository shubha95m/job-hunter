import asyncio
import json
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Locator, Page

from llm_wrapper import generate_action


EXTERNAL_SYSTEM_PROMPT = """You are an intelligent AI agent helping complete an external company job application portal (e.g. Workday, Greenhouse, Lever, Ashby, Pitch N Hire, SmartRecruiters, or custom ATS).

You will receive:
- PORTAL_INFO: URL and detected portal platform
- FORM_FIELDS: visible input/select/textarea/radio/file controls with labels, current values, options, and errors
- PILL_GROUPS: custom radio/pill button groups (e.g. Title, Travel, Pay Frequency, Gender)
- CUSTOM_DROPDOWNS: searchable or custom comboboxes (e.g. Currency Code, Country)
- DROPZONES: file upload dropzones (e.g. Resume, Cover Letter)
- CLIENT_ERRORS: active validation errors on the current page (e.g. "This info is required", "Fields to fix")
- BUTTONS: visible action buttons (e.g., Save and Continue, Next, Review, Submit)
- PROFILE: applicant profile including personal info, address, education, employment history, legal disclosures, and standard answers

CRITICAL MANDATE:
You must fulfill ALL conditions of the current page. If client errors are visible, prioritize fixing those exact fields.

Return ONLY a valid JSON array of actions. No markdown, no commentary.

Supported actions:
[
  {"action": "fill", "id": "field_id", "selector": "optional_css", "value": "answer"},
  {"action": "select", "id": "field_id", "selector": "optional_css", "value": "Exact option text"},
  {"action": "select_custom", "selector": "optional_css", "label": "Currency Code", "value": "INR"},
  {"action": "click_pill", "group": "Title", "option": "Mr."},
  {"action": "check", "id": "field_id", "selector": "optional_css"},
  {"action": "upload", "id": "field_id", "selector": "optional_css", "path": "resume.pdf"},
  {"action": "dismiss_card", "selector": "optional_css"},
  {"action": "click", "text": "Next"},
  {"action": "done"}
]

Rules:
1. Prioritize visible empty required fields and any fields flagged in CLIENT_ERRORS.
2. For pill groups (like Title, Pay Frequency, Travel Internationally, Gender): pick the option matching the profile.
3. For file upload dropzones (Resume / CV), use an "upload" action with profile.resume_path.
4. For checkboxes like 'I agree to privacy policy' or 'Consent to terms', check them.
5. If auto-parsed cards display "Fields to fix", dismiss them if they cannot be completed.
6. When all fields on the current page are filled, end with a 'click' action on the progression button ('Next', 'Save and Continue', 'Review', 'Submit').
7. When on the final review step or when application confirmation is visible, return [{"action": "done"}].
"""


def detect_portal_platform(url: str) -> str:
    """Identify the ATS portal type from URL."""
    u = url.lower()
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "pitchnhire.com" in u or "pnh" in u:
        return "pitchnhire"
    if "icims.com" in u:
        return "icims"
    if "taleo.net" in u:
        return "taleo"
    return "generic"


async def handle_portal_authentication_if_needed(page: Page, profile: dict[str, Any]) -> bool:
    """
    Detects if the company portal requires account creation or login (common in Workday).
    Automatically creates an account or logs in using credentials in profile.phase_2.
    """
    creds = profile.get("phase_2", {}).get("account_credentials", {})
    default_password = creds.get("default_password", "")
    email = profile.get("personal_info", {}).get("email", "")

    create_acct_btn = page.locator(
        "button:has-text('Create Account'), "
        "a:has-text('Create Account'), "
        "[data-automation-id='createAccountButton'], "
        "button:has-text('Sign Up'), "
        "a:has-text('Sign Up')"
    ).first

    sign_in_header = page.locator(
        "h1:has-text('Sign In'), h2:has-text('Sign In'), "
        "h1:has-text('Create Account'), h2:has-text('Create Account'), "
        "[data-automation-id='signInHeader']"
    ).first

    password_fields = page.locator("input[type='password']")
    has_password_input = await password_fields.count() > 0

    if await create_acct_btn.is_visible() or await sign_in_header.is_visible() or has_password_input:
        print("  Detected portal authentication gate (Account / Login)...")

        if await create_acct_btn.is_visible() and not await password_fields.count() >= 2:
            try:
                await create_acct_btn.click(timeout=4000)
                await asyncio.sleep(1.5)
            except Exception:
                pass

        pwd_inputs = await page.locator("input[type='password']").all()
        email_input = page.locator("input[type='email'], input[name*='email' i], [data-automation-id*='email' i]").first

        if len(pwd_inputs) >= 2 and await email_input.is_visible():
            print("  Filling 'Create Account' form...")
            try:
                await email_input.fill(email)
                await pwd_inputs[0].fill(default_password)
                await pwd_inputs[1].fill(default_password)

                terms_chk = page.locator("input[type='checkbox']").first
                if await terms_chk.is_visible() and not await terms_chk.is_checked():
                    await terms_chk.check()

                submit_create = page.locator(
                    "button[data-automation-id*='createAccountSubmit' i], "
                    "button:has-text('Create Account'), "
                    "button:has-text('Register'), "
                    "input[type='submit']"
                ).first
                if await submit_create.is_visible():
                    await submit_create.click(timeout=5000)
                    await asyncio.sleep(2.5)

                error_msg = page.locator(
                    ":text('already exists'), :text('already registered'), :text('User already exists')"
                ).first
                if await error_msg.is_visible():
                    print("  Account already exists. Switching to Sign In...")
                    sign_in_tab = page.locator("a:has-text('Sign In'), button:has-text('Sign In')").first
                    if await sign_in_tab.is_visible():
                        await sign_in_tab.click()
                        await asyncio.sleep(1.5)
                        await _perform_sign_in(page, email, default_password)

                return True
            except Exception as e:
                print(f"  Error during account creation: {e}")

        elif len(pwd_inputs) == 1 and await email_input.is_visible():
            print("  Signing in to existing portal account...")
            return await _perform_sign_in(page, email, default_password)

    return True


async def _perform_sign_in(page: Page, email: str, password: str) -> bool:
    """Helper to fill sign in form."""
    try:
        email_input = page.locator("input[type='email'], input[name*='email' i], [data-automation-id*='email' i]").first
        pwd_input = page.locator("input[type='password']").first
        sign_in_btn = page.locator(
            "button[data-automation-id*='signInSubmit' i], "
            "button:has-text('Sign In'), "
            "button:has-text('Log In'), "
            "input[type='submit']"
        ).first

        if await email_input.is_visible():
            await email_input.fill(email)
        if await pwd_input.is_visible():
            await pwd_input.fill(password)
        if await sign_in_btn.is_visible():
            await sign_in_btn.click(timeout=5000)
            await asyncio.sleep(2)
        return True
    except Exception as e:
        print(f"  Sign in error: {e}")
        return False


async def sense_and_navigate_to_application(page: Page, job_title: str) -> bool:
    """
    Ensures that after landing or logging into the company portal,
    we navigate into the actual application form.
    """
    apply_triggers = (
        "button[data-automation-id='adventureButton'], "
        "[data-automation-id='applyButton'], "
        "a:has-text('Apply Manually'), "
        "button:has-text('Apply Manually'), "
        "button:has-text('Apply Now'), "
        "a:has-text('Apply Now'), "
        "button:has-text('Apply'):not(:has-text('Autofill')), "
        "a:has-text('Apply'):not(:has-text('Autofill'))"
    )

    trigger = page.locator(apply_triggers).first
    if await trigger.count() > 0 and await trigger.is_visible():
        try:
            print("  Clicking portal 'Apply' entry point...")
            await trigger.click(timeout=5000)
            await asyncio.sleep(2)
        except Exception:
            pass

    manual_btn = page.locator(
        "button:has-text('Apply Manually'), a:has-text('Apply Manually'), [data-automation-id='applyManually']"
    ).first
    if await manual_btn.count() > 0 and await manual_btn.is_visible():
        try:
            print("  Selecting 'Apply Manually' for direct control...")
            await manual_btn.click(timeout=5000)
            await asyncio.sleep(2)
        except Exception:
            pass

    return True


async def wait_for_processing_spinners(page: Page, max_wait_sec: int = 30) -> None:
    """
    Waits for async resume parsing or submission spinners to complete.
    e.g. 'Your resume is being processed. It will take some time to complete.'
    """
    spinner_text_patterns = [
        "Your resume is being processed",
        "will take some time to complete",
        "Processing your resume",
        "Uploading...",
        "Please wait",
    ]
    spinner_selectors = (
        "[class*='spinner' i], [class*='loading' i], [role='progressbar'], "
        ".loader, [aria-busy='true'], svg[class*='animate-spin' i]"
    )

    elapsed = 0
    poll_interval = 1.5

    while elapsed < max_wait_sec:
        is_text_visible = False
        for text in spinner_text_patterns:
            loc = page.locator(f":text('{text}')").first
            if await loc.count() > 0 and await loc.is_visible():
                is_text_visible = True
                break

        spinner_loc = page.locator(spinner_selectors).first
        has_spinner = await spinner_loc.count() > 0 and await spinner_loc.is_visible()

        if is_text_visible or has_spinner:
            print(f"  [Wait] Processing spinner / resume analysis active ({elapsed:.1f}s)... waiting for completion")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            if elapsed > 0:
                print("  [Wait] Processing spinner completed. Resuming form filling.")
            break


async def extract_external_form_context(page: Page) -> dict[str, Any]:
    """
    Comprehensive DOM extraction tailored for modern ATS architectures:
    - Standard Inputs & Textareas
    - Select Dropdowns & Custom Comboboxes (e.g. Currency Code)
    - Pill / Tag Button Groups (e.g. Title, Pay Frequency, Travel)
    - File Dropzones (Resume, Cover Letter)
    - Checkboxes (Terms, Consent, Declarations)
    - Broken Auto-Parsed Cards ("Fields to fix: N")
    - Client Validation Errors (e.g. "This info is required", red borders)
    - Action / Progression Buttons
    """
    return await page.evaluate(
        """() => {
        function isVisible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }

        function hasRedErrorBorder(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const borderCol = style.borderColor || '';
            const isRed = borderCol.includes('rgb(2') || borderCol.includes('red') || borderCol.includes('rgb(255');
            const classHasErr = /error|invalid|has-error|border-red/i.test(el.className || '');
            const ariaInvalid = el.getAttribute('aria-invalid') === 'true';
            return isRed || classHasErr || ariaInvalid;
        }

        function getLabel(el) {
            if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${el.id}"]`);
                if (labelEl) return labelEl.innerText.trim();
            }
            const parentLabel = el.closest('label');
            if (parentLabel) return parentLabel.innerText.trim();
            
            const container = el.closest('[data-automation-id*="formField"], .form-group, .field, [class*="form-item"], [class*="form-group"], div');
            if (container) {
                const label = container.querySelector('label, [data-automation-id*="label"], h3, h4, h5, [class*="label"]');
                if (label && label !== el) return label.innerText.trim();
            }
            return el.placeholder || el.name || '';
        }

        const fields = [];
        const seenIds = new Set();

        // 1. Text Inputs, Email, Tel, Number, Textarea
        const inputs = Array.from(document.querySelectorAll(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="radio"]):not([type="checkbox"]):not([type="file"]), textarea'
        ));

        for (const input of inputs) {
            if (!isVisible(input)) continue;
            const id = input.id || input.name || input.getAttribute('data-automation-id') || '';
            const key = id || (input.name || '') + input.className;
            if (seenIds.has(key)) continue;
            seenIds.add(key);

            const container = input.closest('div');
            const errEl = container ? container.querySelector('[class*="error" i], :text("is required"), :text("This info is required")') : null;
            const hasErr = hasRedErrorBorder(input) || (container && hasRedErrorBorder(container)) || !!errEl;

            fields.push({
                tag: input.tagName.toLowerCase(),
                type: input.type || 'text',
                id: id,
                name: input.name || '',
                label: getLabel(input),
                value: input.value || '',
                required: input.required || input.getAttribute('aria-required') === 'true' || getLabel(input).includes('*'),
                has_error: hasErr,
                error_text: errEl ? errEl.innerText.trim() : ''
            });
        }

        // 2. Select Dropdowns
        const selects = Array.from(document.querySelectorAll('select'));
        for (const sel of selects) {
            if (!isVisible(sel)) continue;
            const id = sel.id || sel.name || '';
            const options = Array.from(sel.options).map(o => o.text.trim()).filter(Boolean);
            fields.push({
                tag: 'select',
                id: id,
                label: getLabel(sel),
                value: sel.value,
                options: options.slice(0, 30),
                required: sel.required || sel.getAttribute('aria-required') === 'true' || getLabel(sel).includes('*'),
                has_error: hasRedErrorBorder(sel)
            });
        }

        // 3. Custom Comboboxes / Dropdowns (e.g. Currency Code, Country, State)
        const customDropdowns = [];
        const comboTriggers = Array.from(document.querySelectorAll(
            '[role="combobox"], [aria-haspopup="listbox"], [class*="select__control"], [class*="custom-select"], ' +
            'button[data-automation-id*="Dropdown" i], [data-automation-id*="dropdown" i], ' +
            'button[data-automation-id*="country" i], button[data-automation-id*="region" i], ' +
            'div:has(> svg):has-text("Currency")'
        ));
        for (const combo of comboTriggers) {
            if (!isVisible(combo)) continue;
            const label = getLabel(combo);
            const val = combo.innerText.trim();
            const hasErr = hasRedErrorBorder(combo) || combo.innerHTML.includes('This info is required');
            customDropdowns.push({
                label: label || 'Custom Dropdown',
                current_value: val,
                has_error: hasErr
            });
        }

        // 4. Pill / Tag Button Groups (e.g. Title, Pay Frequency, Travel Internationally, Gender)
        const pillGroups = [];
        // Look for groups of sibling buttons/pills under a question/section header
        const candidateGroups = Array.from(document.querySelectorAll('div, fieldset, section'));
        for (const grp of candidateGroups) {
            if (!isVisible(grp)) continue;
            // Find child buttons/pills
            const buttons = Array.from(grp.querySelectorAll(':scope > button, :scope > div > button, :scope > [role="radio"], :scope > [class*="pill"], :scope > [class*="chip"]'))
                .filter(isVisible);

            // If we have 2 to 8 sibling buttons (like [Dr.][Miss][Mr.] or [No][Yes] or [Daily][Weekly]...)
            if (buttons.length >= 2 && buttons.length <= 8) {
                // Get the label preceding or within this group
                let label = '';
                const prev = grp.previousElementSibling;
                if (prev && isVisible(prev)) label = prev.innerText.trim();
                if (!label) {
                    const header = grp.querySelector('label, h3, h4, h5, [class*="title"], [class*="label"]');
                    if (header) label = header.innerText.trim();
                }
                if (!label && grp.parentElement) {
                    const pHeader = grp.parentElement.querySelector('label, h3, h4, h5');
                    if (pHeader) label = pHeader.innerText.trim();
                }

                if (label && label.length < 80) {
                    const options = buttons.map(b => {
                        const txt = b.innerText.trim();
                        const isSelected = /active|selected|checked|bg-blue/i.test(b.className || '') ||
                                           b.getAttribute('aria-checked') === 'true' ||
                                           b.getAttribute('aria-pressed') === 'true';
                        return { text: txt, is_selected: isSelected };
                    }).filter(o => o.text.length > 0 && o.text.length < 30);

                    if (options.length >= 2) {
                        const err = grp.innerText.includes('This info is required') || hasRedErrorBorder(grp);
                        pillGroups.push({
                            label: label,
                            options: options,
                            has_error: err
                        });
                    }
                }
            }
        }

        // Deduplicate pill groups by label
        const uniquePillGroups = [];
        const seenPillLabels = new Set();
        for (const pg of pillGroups) {
            const cleanLabel = pg.label.replace(/\\*|:/g, '').trim().toLowerCase();
            if (!seenPillLabels.has(cleanLabel)) {
                seenPillLabels.add(cleanLabel);
                uniquePillGroups.push(pg);
            }
        }

        // 5. File Upload Dropzones
        const dropzones = [];
        const dropzoneEls = Array.from(document.querySelectorAll(
            '[class*="dropzone" i], [class*="upload" i], :text("Drop Resume Here"), :text("Drop Cover Letter Here")'
        ));
        for (const dz of dropzoneEls) {
            const container = dz.closest('div');
            if (!container || !isVisible(container)) continue;
            const text = container.innerText || '';
            if (text.includes('Resume') || text.includes('Cover Letter')) {
                const isResume = text.includes('Resume');
                const isRequired = text.includes('*') || text.includes('This info is required');
                const hasErr = hasRedErrorBorder(container) || text.includes('This info is required');
                dropzones.push({
                    type: isResume ? 'resume' : 'cover_letter',
                    label: isResume ? 'Resume Dropzone' : 'Cover Letter Dropzone',
                    required: isRequired,
                    has_error: hasErr
                });
            }
        }

        // 6. Checkboxes & Native Radios
        const checkables = Array.from(document.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="checkbox"]'));
        const checkboxes = [];
        for (const chk of checkables) {
            if (!isVisible(chk)) continue;
            const label = getLabel(chk);
            const isChecked = chk.checked || chk.getAttribute('aria-checked') === 'true';
            checkboxes.push({
                type: chk.type || 'checkbox',
                id: chk.id || chk.name || '',
                label: label,
                checked: isChecked,
                required: chk.required || chk.getAttribute('aria-required') === 'true' || label.includes('*'),
                has_error: hasRedErrorBorder(chk)
            });
        }

        // 7. Broken Auto-Parsed Cards (e.g. "Selenium Professional Certification ... Fields to fix: 1")
        const brokenCards = [];
        const fixEls = Array.from(document.querySelectorAll(':text("Fields to fix")'));
        for (const el of fixEls) {
            const card = el.closest('[class*="item"], [class*="card"], [class*="box"], div');
            if (card && isVisible(card)) {
                brokenCards.push({
                    text: card.innerText.trim().slice(0, 100),
                    has_error: true
                });
            }
        }

        // 8. Action Buttons
        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]'))
            .filter(isVisible)
            .map(b => (b.innerText || b.value || b.getAttribute('aria-label') || '').trim())
            .filter(t => t.length > 0 && t.length < 50);

        const uniqueButtons = Array.from(new Set(buttons));

        // 9. Client Validation Errors Across Entire Page
        const errorNodes = Array.from(document.querySelectorAll(
            '.error, [class*="error" i], [data-automation-id*="error" i], [role="alert"], ' +
            ':text("This info is required"), :text("Fields to fix"), :text("Please fill"), :text("is required")'
        )).filter(isVisible);

        const rawErrors = errorNodes.map(e => e.innerText.trim()).filter(Boolean);
        const uniqueErrors = Array.from(new Set(rawErrors)).filter(e => e.length > 3 && e.length < 150);

        return {
            url: window.location.href,
            title: document.title,
            fields: fields.slice(0, 45),
            custom_dropdowns: customDropdowns.slice(0, 10),
            pill_groups: uniquePillGroups.slice(0, 15),
            dropzones: dropzones.slice(0, 5),
            checkboxes: checkboxes.slice(0, 20),
            broken_cards: brokenCards.slice(0, 5),
            buttons: uniqueButtons.slice(0, 15),
            errors: uniqueErrors.slice(0, 10)
        };
    }"""
    )


async def handle_page_profile_import_and_resume(page: Page, profile: dict[str, Any]) -> int:
    """
    Checks for:
    1. 'Apply With LinkedIn' button / link and triggers profile autofill.
    2. 'Upload resume' / 'Drop resume' / file input and attaches resume (respecting size limits like 1MB max).
    Returns count of import/upload actions executed.
    """
    actions_taken = 0

    # 1. Check for 'Apply With LinkedIn'
    import_prefs = profile.get("phase_2", {}).get("import_preferences", {})
    should_try_linkedin = import_prefs.get("apply_with_linkedin", True)

    if should_try_linkedin:
        linkedin_btn = page.locator(
            "button:has-text('Apply With LinkedIn'), "
            "a:has-text('Apply With LinkedIn'), "
            "button:has-text('Apply with LinkedIn'), "
            "a:has-text('Apply with LinkedIn'), "
            "[data-automation-id*='applyWithLinkedIn' i], "
            "[data-automation-id*='linkedin' i]"
        ).first

        if await linkedin_btn.count() > 0 and await linkedin_btn.is_visible():
            print("  [Profile Import] Found 'Apply With LinkedIn' on page! Triggering 1-click import...")
            try:
                # Some portals open a LinkedIn OAuth popup window
                async with page.context.expect_page(timeout=4500) as popup_info:
                    await linkedin_btn.click(timeout=3000)
                popup = await popup_info.value
                print(f"  -> Opened LinkedIn OAuth popup: {popup.url}")
                await popup.wait_for_load_state("domcontentloaded", timeout=6000)
                allow_btn = popup.locator(
                    "button:has-text('Allow'), button:has-text('Authorize'), "
                    "button:has-text('Sign In'), button:has-text('Continue as'), "
                    "input[type='submit']"
                ).first
                if await allow_btn.is_visible():
                    print("  -> Authorizing LinkedIn profile import...")
                    await allow_btn.click()
                    await asyncio.sleep(2)
                actions_taken += 1
            except Exception:
                # If no popup opened, it's an in-page import
                actions_taken += 1
                await asyncio.sleep(2)

            await wait_for_processing_spinners(page)

    # 2. Check for Resume Upload triggers (link, button, dropzone, input)
    upload_trigger = page.locator(
        "a:has-text('Upload resume'), "
        "button:has-text('Upload resume'), "
        "a:has-text('Upload Resume'), "
        "button:has-text('Upload Resume'), "
        ":text('Drop Resume Here'), "
        ":text('Drop resume'), "
        "[data-automation-id*='file-upload' i], "
        "[data-automation-id*='upload' i], "
        "[class*='dropzone']:has-text('Resume')"
    ).first

    file_inputs = page.locator("input[type='file']")
    has_file_input = await file_inputs.count() > 0
    has_upload_trigger = await upload_trigger.count() > 0 and await upload_trigger.is_visible()

    if has_upload_trigger or has_file_input:
        # Determine the best resume file based on size constraints (e.g. Workday 1MB limit)
        page_html = await page.content()
        is_1mb_limit = "1mb" in page_html.lower() or "1 mb" in page_html.lower()

        resume_path = profile.get("resume_path", "")
        if is_1mb_limit:
            under1mb = profile.get("resume_under1mb_path", "")
            if under1mb and not os.path.isabs(under1mb):
                under1mb = os.path.abspath(under1mb)
            if under1mb and os.path.exists(under1mb):
                resume_path = under1mb
                print(f"  [Resume Upload] Portal has 1MB file limit. Using optimized resume: {os.path.basename(resume_path)}")

        if resume_path and not os.path.isabs(resume_path):
            resume_path = os.path.abspath(resume_path)

        if os.path.exists(resume_path):
            print(f"  [Resume Upload] Providing resume file: {os.path.basename(resume_path)}")
            # Try direct set_input_files first
            if has_file_input:
                try:
                    await file_inputs.first.set_input_files(resume_path)
                    actions_taken += 1
                    print("  -> Resume attached directly to input[type='file'].")
                    await asyncio.sleep(2)
                    await wait_for_processing_spinners(page)
                except Exception as e:
                    print(f"  Direct file input warning: {e}")

            # If that didn't trigger or no file input, try clicking the upload link/button
            if has_upload_trigger and actions_taken == 0:
                try:
                    async with page.expect_file_chooser(timeout=4000) as fc_info:
                        await upload_trigger.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(resume_path)
                    actions_taken += 1
                    print("  -> Resume attached via file chooser trigger.")
                    await asyncio.sleep(2)
                    await wait_for_processing_spinners(page)
                except Exception as e:
                    print(f"  File chooser warning: {e}")

    return actions_taken


async def handle_workday_and_enterprise_fields(page: Page, profile: dict[str, Any]) -> int:
    """
    Guarantees that ALL standard fields on the current page are populated from candidate profile:
    - Country (Workday custom dropdown)
    - First Name / Last Name
    - Address Line 1 / City / State / Postal Code
    - Phone Number & Phone Device Type (Mobile)
    - Email Address
    - How did you hear about us? (LinkedIn / Job Board)
    """
    fields_filled = 0
    p2 = profile.get("phase_2", {})
    addr = p2.get("address", {})
    personal = profile.get("personal_info", {})

    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    country = addr.get("country", "")
    street = addr.get("street_address_line1", "")
    city = addr.get("city", "")
    state = addr.get("state_province", "")
    postal = addr.get("postal_code", "")

    # 1. Country Selection (Workday custom prompt/dropdown)
    try:
        country_btn = page.locator(
            "button[data-automation-id='countryDropdown'], "
            "button[data-automation-id*='country' i], "
            "[data-automation-id='select-selected-item']:near(:text('Country'))"
        ).first
        if await country_btn.count() > 0 and await country_btn.is_visible():
            current_text = await country_btn.inner_text()
            if country.lower() not in current_text.lower():
                print(f"  [Auto-Fill] Setting Country -> [{country}]")
                await country_btn.click(timeout=3000)
                await asyncio.sleep(0.5)
                search = page.locator("input[type='text']:visible, input[type='search']:visible").last
                if await search.count() > 0:
                    await search.fill(country)
                    await search.press("Enter")
                    await asyncio.sleep(0.4)
                opt = page.locator(f"[role='option']:has-text('{country}'), li:has-text('{country}')").first
                if await opt.is_visible():
                    await opt.click(timeout=3000)
                fields_filled += 1
    except Exception:
        pass

    # 2. Text fields: First Name, Last Name, Address, City, Postal, Phone, Email
    text_mappings = [
        ("input[data-automation-id*='firstName' i], input[name*='firstName' i], input[id*='firstName' i]", first_name),
        ("input[data-automation-id*='lastName' i], input[name*='lastName' i], input[id*='lastName' i]", last_name),
        ("input[data-automation-id*='addressLine1' i], input[name*='addressLine1' i]", street),
        ("input[data-automation-id*='city' i], input[name*='city' i]", city),
        ("input[data-automation-id*='postalCode' i], input[name*='postalCode' i]", postal),
        ("input[data-automation-id*='phone' i], input[name*='phone' i], input[type='tel']", phone),
        ("input[data-automation-id*='email' i], input[type='email']:not([name*='user']):not([name*='login'])", email),
    ]

    for sel, val in text_mappings:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                current_val = await loc.input_value()
                if not current_val:
                    await loc.fill(val, timeout=3000)
                    fields_filled += 1
        except Exception:
            pass

    # 3. State / Province
    try:
        state_loc = page.locator(
            "button[data-automation-id*='countryRegion' i], "
            "button[data-automation-id*='region' i], "
            "input[name*='state' i]"
        ).first
        if await state_loc.count() > 0 and await state_loc.is_visible():
            tag_name = await state_loc.evaluate("el => el.tagName.toLowerCase()")
            if tag_name == "input":
                if not await state_loc.input_value():
                    await state_loc.fill(state, timeout=3000)
                    fields_filled += 1
            else:
                txt = await state_loc.inner_text()
                if state.lower() not in txt.lower():
                    await state_loc.click(timeout=3000)
                    await asyncio.sleep(0.5)
                    opt = page.locator(f"[role='option']:has-text('{state}'), li:has-text('{state}')").first
                    if await opt.is_visible():
                        await opt.click(timeout=3000)
                        fields_filled += 1
    except Exception:
        pass

    # 4. Phone Device Type (Mobile)
    try:
        phone_type_btn = page.locator(
            "button[data-automation-id*='phone-device-type' i], "
            "button[data-automation-id*='deviceType' i]"
        ).first
        if await phone_type_btn.count() > 0 and await phone_type_btn.is_visible():
            txt = await phone_type_btn.inner_text()
            if "mobile" not in txt.lower():
                await phone_type_btn.click(timeout=3000)
                await asyncio.sleep(0.5)
                opt = page.locator("[role='option']:has-text('Mobile'), li:has-text('Mobile')").first
                if await opt.is_visible():
                    await opt.click(timeout=3000)
                    fields_filled += 1
    except Exception:
        pass

    # 5. Source / How did you hear about us?
    try:
        source_btn = page.locator(
            "button[data-automation-id*='source' i], "
            "select[name*='source' i]"
        ).first
        if await source_btn.count() > 0 and await source_btn.is_visible():
            txt = await source_btn.inner_text()
            if not txt or "select" in txt.lower():
                await source_btn.click(timeout=3000)
                await asyncio.sleep(0.5)
                opt = page.locator("[role='option']:has-text('LinkedIn'), li:has-text('LinkedIn')").first
                if await opt.is_visible():
                    await opt.click(timeout=3000)
                    fields_filled += 1
    except Exception:
        pass

    return fields_filled


async def apply_ats_specialized_fixes(page: Page, context: dict[str, Any], profile: dict[str, Any]) -> int:
    """
    Directly handles the specialized ATS components that trip up standard form fillers:
    1. Resume Dropzone / File attachment
    2. Pill Button Groups (Title: Mr., Travel: Yes/No, Pay Frequency: Yearly, etc.)
    3. Custom Dropdowns (Currency Code: INR, etc.)
    4. Broken Auto-Parsed Cards ("Fields to fix: 1" dismissal)
    5. Required / Agreement Checkboxes
    6. Preferred Skills Tags
    Returns the count of specialized fixes applied.
    """
    fixes_applied = 0
    resume_path = profile.get("resume_path", "")
    if resume_path and not os.path.isabs(resume_path):
        resume_path = os.path.abspath(resume_path)

    # -------------------------------------------------------------------------
    # 1. Resume Dropzone & File Attachment
    # -------------------------------------------------------------------------
    dropzones = context.get("dropzones", [])
    has_resume_error = any(dz.get("type") == "resume" and dz.get("has_error") for dz in dropzones)
    has_any_resume_dropzone = any(dz.get("type") == "resume" for dz in dropzones)

    if (has_resume_error or has_any_resume_dropzone) and resume_path and os.path.exists(resume_path):
        print(f"  [ATS Fix] Handling Resume upload dropzone with: {os.path.basename(resume_path)}")
        try:
            # First attempt: Direct Playwright set_input_files on any input[type='file']
            file_inputs = page.locator("input[type='file']")
            if await file_inputs.count() > 0:
                await file_inputs.first.set_input_files(resume_path)
                fixes_applied += 1
                print("  -> Resume attached directly via file input.")
                await asyncio.sleep(2)
                await wait_for_processing_spinners(page)
            else:
                # Second attempt: Click 'Upload Resume' / dropzone with file chooser listener
                upload_trigger = page.locator(
                    "button:has-text('Upload Resume'), "
                    "a:has-text('Upload Resume'), "
                    ":text('Drop Resume Here'), "
                    "[class*='dropzone']:has-text('Resume')"
                ).first

                if await upload_trigger.is_visible():
                    try:
                        async with page.expect_file_chooser(timeout=4000) as fc_info:
                            await upload_trigger.click()
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(resume_path)
                        fixes_applied += 1
                        print("  -> Resume attached via file chooser trigger.")
                        await asyncio.sleep(2)
                        await wait_for_processing_spinners(page)
                    except Exception:
                        pass
        except Exception as e:
            print(f"  Resume upload fix warning: {e}")

    # -------------------------------------------------------------------------
    # 2. Pill Button Groups (Title, Travel, Pay Frequency, Gender, Authorization)
    # -------------------------------------------------------------------------
    pill_groups = context.get("pill_groups", [])
    for pg in pill_groups:
        label = pg.get("label", "").lower()
        options = pg.get("options", [])
        has_error = pg.get("has_error", False)
        is_any_selected = any(o.get("is_selected") for o in options)

        # Target value to select
        target_option = None

        if "title" in label or "salutation" in label:
            target_option = profile.get("personal_info", {}).get("title", "Mr.")
        elif "travel" in label:
            target_option = profile.get("standard_answers", {}).get("travel_internationally", "Yes")
        elif "frequency" in label or "pay frequency" in label:
            target_option = profile.get("standard_answers", {}).get("pay_frequency", "Yearly")
        elif "gender" in label:
            target_option = profile.get("standard_answers", {}).get("gender", "Male")
        elif "authorized" in label or "legal" in label:
            target_option = "Yes" if profile.get("standard_answers", {}).get("legally_authorized", True) else "No"
        elif "sponsorship" in label:
            target_option = "Yes" if profile.get("standard_answers", {}).get("require_sponsorship", True) else "No"

        if target_option and (not is_any_selected or has_error):
            # Locate button with matching option text within that container
            print(f"  [ATS Fix] Selecting pill group '{pg.get('label')}': clicking [{target_option}]")
            try:
                # Find the button matching the target option
                btn = page.locator(
                    f"button:has-text('{target_option}'), "
                    f"[role='radio']:has-text('{target_option}'), "
                    f"[class*='pill']:has-text('{target_option}')"
                ).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=3000)
                    fixes_applied += 1
                    await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Pill click warning: {e}")

    # -------------------------------------------------------------------------
    # 3. Custom Dropdowns (Currency Code, Country)
    # -------------------------------------------------------------------------
    custom_dropdowns = context.get("custom_dropdowns", [])
    for cd in custom_dropdowns:
        lbl = cd.get("label", "").lower()
        has_err = cd.get("has_error", False)
        val = cd.get("current_value", "")

        if ("currency" in lbl or "currency code" in lbl) and (has_err or not val):
            target_currency = profile.get("standard_answers", {}).get("currency_code", "INR")
            print(f"  [ATS Fix] Resolving Custom Dropdown '{cd.get('label')}' -> Selecting '{target_currency}'")
            try:
                # Find dropdown element near Currency Code label
                trigger = page.locator(
                    "[role='combobox'], [aria-haspopup='listbox'], div:has(> svg):near(:text('Currency Code'))"
                ).first
                if await trigger.count() > 0 and await trigger.is_visible():
                    await trigger.click(timeout=3000)
                    await asyncio.sleep(0.6)

                    # Look for search input inside dropdown popup
                    search_box = page.locator("input[type='text']:visible, input[type='search']:visible").last
                    if await search_box.count() > 0:
                        try:
                            await search_box.fill(target_currency)
                            await asyncio.sleep(0.5)
                            await search_box.press("Enter")
                        except Exception:
                            pass

                    # Click matching option
                    opt = page.locator(
                        f"[role='option']:has-text('{target_currency}'), "
                        f"li:has-text('{target_currency}'), "
                        f"div:has-text('{target_currency}')"
                    ).first
                    if await opt.count() > 0 and await opt.is_visible():
                        await opt.click(timeout=3000)
                        fixes_applied += 1
                        await asyncio.sleep(0.5)
            except Exception as e:
                print(f"  Custom dropdown fix warning: {e}")

    # -------------------------------------------------------------------------
    # 4. Broken Auto-Parsed Cards ("Fields to fix: N")
    # -------------------------------------------------------------------------
    broken_cards = context.get("broken_cards", [])
    if broken_cards:
        print(f"  [ATS Fix] Detected {len(broken_cards)} incomplete parsed card(s) with 'Fields to fix'. Dismissing blocking items...")
        try:
            fix_indicators = await page.locator(":text('Fields to fix')").all()
            for ind in fix_indicators:
                if await ind.is_visible():
                    card = ind.locator("xpath=ancestor::*[contains(@class, 'card') or contains(@class, 'box') or contains(@class, 'item') or self::div][1]")
                    dismiss_btn = card.locator(
                        "button:has-text('x'), button:has-text('×'), button:has-text('✕'), [aria-label*='delete' i], [aria-label*='remove' i]"
                    ).first
                    if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                        await dismiss_btn.click(timeout=3000)
                        fixes_applied += 1
                        print("  -> Dismissed incomplete parsed item blocking submission.")
                        await asyncio.sleep(1)
        except Exception as e:
            print(f"  Broken card dismissal warning: {e}")

    # -------------------------------------------------------------------------
    # 5. Checkboxes (Terms, Consent, Declarations)
    # -------------------------------------------------------------------------
    checkboxes = context.get("checkboxes", [])
    for chk in checkboxes:
        lbl = chk.get("label", "").lower()
        is_checked = chk.get("checked", False)
        is_required = chk.get("required", False)
        has_err = chk.get("has_error", False)

        is_consent = any(w in lbl for w in ["agree", "consent", "terms", "policy", "certify", "acknowledge", "declaration"])

        if (is_required or is_consent or has_err) and not is_checked:
            cid = chk.get("id")
            print(f"  [ATS Fix] Checking mandatory/consent checkbox: '{chk.get('label')[:40]}...'")
            try:
                chk_loc = page.locator(f"[id='{cid}']") if cid else page.locator(f"input[type='checkbox']:near(:text('{chk.get('label')[:20]}'))").first
                if await chk_loc.count() > 0 and await chk_loc.is_visible():
                    await chk_loc.check(force=True, timeout=3000)
                    fixes_applied += 1
                else:
                    # Click parent label
                    lbl_loc = page.locator(f"label:has-text('{chk.get('label')[:25]}')").first
                    if await lbl_loc.count() > 0 and await lbl_loc.is_visible():
                        await lbl_loc.click(timeout=3000)
                        fixes_applied += 1
            except Exception as e:
                print(f"  Checkbox fix warning: {e}")

    # -------------------------------------------------------------------------
    # 6. Preferred Skills Tags (e.g. "QA Automation +")
    # -------------------------------------------------------------------------
    user_skills = [s.lower() for s in profile.get("skills", [])]
    try:
        preferred_skill_btns = page.locator(
            "button:has-text('+'), [class*='skill']:has-text('+'), [class*='chip']:has-text('+')"
        )
        count = await preferred_skill_btns.count()
        for i in range(min(count, 5)):
            btn = preferred_skill_btns.nth(i)
            if await btn.is_visible():
                txt = (await btn.inner_text()).lower().replace("+", "").strip()
                if any(us in txt or txt in us for us in user_skills) or "automation" in txt or "qa" in txt:
                    print(f"  [ATS Fix] Adding preferred matching skill: [{txt}]")
                    await btn.click(timeout=2000)
                    fixes_applied += 1
                    await asyncio.sleep(0.3)
    except Exception:
        pass

    return fixes_applied


async def satisfy_current_page_and_advance(
    page: Page, profile: dict[str, Any], max_healing_attempts: int = 4
) -> str:
    """
    Enforces the Core Phase-2 Contract:
    Ensures that ALL conditions of the CURRENT page are satisfied.
    If clicking Next/Submit triggers client validation errors, it:
    1. Inspects the errors.
    2. Applies targeted fixes to the errored fields (dropzone, pill radios, selects, checkboxes, inputs).
    3. Retries clicking Next/Submit.
    4. Confirms that the page actually transitioned before returning!

    Returns:
    - 'DONE' if the entire application was submitted
    - 'ADVANCED' if the page was successfully satisfied and progressed
    - 'STUCK' if unable to satisfy page after max healing attempts
    """
    platform = detect_portal_platform(page.url)

    for attempt in range(1, max_healing_attempts + 1):
        print(f"\n  --- Satisfying Page Conditions (Attempt {attempt}/{max_healing_attempts}) ---")

        # 0. Check immediate success
        if await is_external_submission_success(page):
            return "DONE"

        # 1. Wait for processing spinners (resume parsing, etc.)
        await wait_for_processing_spinners(page)

        # 1b. Profile Import & Resume Upload triggers (e.g. Apply With LinkedIn, Upload resume link/dropzone)
        import_count = await handle_page_profile_import_and_resume(page, profile)
        if import_count > 0:
            await asyncio.sleep(1.5)
            await wait_for_processing_spinners(page)

        # 1c. Pre-populate all standard Workday & Enterprise fields on this page (Country, Name, Address, Phone, Email, Source)
        autofilled_count = await handle_workday_and_enterprise_fields(page, profile)
        if autofilled_count > 0:
            print(f"  [Auto-Fill] Populated {autofilled_count} standard profile field(s) on current page.")
            await asyncio.sleep(0.5)

        # 2. Extract DOM Context
        context = await extract_external_form_context(page)
        fields = context.get("fields", [])
        buttons = context.get("buttons", [])
        errors = context.get("errors", [])

        if errors:
            print(f"  [Client Errors Detected]: {errors}")

        # 3. Apply ATS Specialized Fixes (dropzone, pill buttons, custom comboboxes, broken cards)
        specialized_count = await apply_ats_specialized_fixes(page, context, profile)
        if specialized_count > 0:
            print(f"  Applied {specialized_count} specialized ATS fix(es).")
            await asyncio.sleep(1)

        # 4. Fill remaining empty or errored text inputs/textareas using LLM
        empty_or_errored_fields = [
            f for f in fields
            if (f.get("required") and not f.get("value")) or f.get("has_error")
        ]

        if empty_or_errored_fields:
            print(f"  Consulting AI for {len(empty_or_errored_fields)} unfilled/errored field(s)...")
            prompt = f"""{EXTERNAL_SYSTEM_PROMPT}

PORTAL_INFO:
Platform: {platform}
URL: {context.get('url')}
Title: {context.get('title')}

FORM_FIELDS:
{json.dumps(fields, indent=2)}

CLIENT_ERRORS:
{json.dumps(errors, indent=2)}

BUTTONS:
{json.dumps(buttons, indent=2)}

PROFILE:
{json.dumps(profile, indent=2)}
"""
            actions = await generate_action(prompt)
            if actions and isinstance(actions, list):
                print(f"  AI returned {len(actions)} action(s): {actions}")
                await _execute_actions(page, actions, profile)

        # 5. Check if we reached final submission success before clicking progression
        if await is_external_submission_success(page):
            return "DONE"

        # 6. Locate Progression Button
        progression_button_labels = [
            "Submit Application",
            "Submit application",
            "Submit",
            "Review",
            "Save and Continue",
            "Save & Continue",
            "Next",
            "Continue",
            "Proceed"
        ]

        target_btn = None
        target_label = ""
        for lbl in progression_button_labels:
            btn = page.locator(
                f"button:has-text('{lbl}'), input[type='submit'][value='{lbl}'], [role='button']:has-text('{lbl}')"
            ).first
            if await btn.count() > 0 and await btn.is_visible():
                target_btn = btn
                target_label = lbl
                break

        if not target_btn:
            print("  No obvious progression button visible. Checking page state...")
            await asyncio.sleep(2)
            if await is_external_submission_success(page):
                return "DONE"
            return "ADVANCED"

        # 7. Record current page snapshot before clicking
        pre_url = page.url
        pre_title = await page.title()
        pre_errors_count = len(errors)

        print(f"  -> Clicking progression button [{target_label}]...")
        try:
            await target_btn.click(timeout=5000)
        except Exception as e:
            print(f"  Progression click error: {e}")

        # 8. Wait for client validation or page transition
        await asyncio.sleep(2.5)
        await wait_for_processing_spinners(page)

        # 9. Verify Result
        # a) Check submission success
        if await is_external_submission_success(page):
            return "DONE"

        # b) Check if URL changed
        post_url = page.url
        if post_url != pre_url and "login" not in post_url.lower():
            print(f"  [Progression Verified] Page advanced to new URL: {post_url}")
            return "ADVANCED"

        # c) Inspect new page errors
        post_context = await extract_external_form_context(page)
        post_errors = post_context.get("errors", [])
        post_fields = post_context.get("fields", [])

        # Did the previous fields disappear and new fields appear?
        pre_ids = {f.get("id") for f in fields if f.get("id")}
        post_ids = {f.get("id") for f in post_fields if f.get("id")}
        if pre_ids and post_ids and not (pre_ids & post_ids):
            print("  [Progression Verified] Form fields transitioned to next step.")
            return "ADVANCED"

        if post_errors:
            print(f"  [Self-Healing] Page NOT satisfied! Still on same page with {len(post_errors)} client error(s):")
            for err in post_errors:
                print(f"     * {err}")
            print(f"  -> Retrying self-healing loop (attempt {attempt + 1}/{max_healing_attempts})...")
            await asyncio.sleep(1)
        else:
            # No visible errors and heading changed or content settled
            print("  Page conditions satisfied. Moving forward.")
            return "ADVANCED"

    print("  [Warning] Max healing attempts reached on current page.")
    return "STUCK"


async def _execute_actions(page: Page, actions: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    """Executes actions returned by LLM on the external portal page."""
    resume_path = profile.get("resume_path", "")
    if resume_path and not os.path.isabs(resume_path):
        resume_path = os.path.abspath(resume_path)

    for action in actions:
        act_type = action.get("action")
        field_id = action.get("id") or ""
        selector = action.get("selector") or ""
        val = action.get("value", "")

        try:
            # 1. Fill input or textarea
            if act_type == "fill":
                locator = _resolve_external_locator(page, field_id, selector)
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.fill(str(val), timeout=3000)

            # 2. Select standard dropdown
            elif act_type == "select":
                locator = _resolve_external_locator(page, field_id, selector)
                if await locator.count() > 0:
                    try:
                        await locator.select_option(label=str(val), timeout=3000)
                    except Exception:
                        await locator.click()
                        await asyncio.sleep(0.5)
                        opt = page.locator(f"[role='option']:has-text('{val}'), li:has-text('{val}')").first
                        if await opt.is_visible():
                            await opt.click()

            # 3. Custom dropdown selection
            elif act_type == "select_custom":
                lbl = action.get("label", "")
                trigger = page.locator(f"[role='combobox']:near(:text('{lbl}')), div:near(:text('{lbl}'))").first
                if await trigger.count() > 0 and await trigger.is_visible():
                    await trigger.click(timeout=3000)
                    await asyncio.sleep(0.5)
                    opt = page.locator(f"[role='option']:has-text('{val}'), li:has-text('{val}'), div:has-text('{val}')").first
                    if await opt.count() > 0 and await opt.is_visible():
                        await opt.click()

            # 4. Click pill button
            elif act_type == "click_pill":
                opt_text = action.get("option", "")
                btn = page.locator(f"button:has-text('{opt_text}'), [role='radio']:has-text('{opt_text}')").first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=3000)

            # 5. Check checkbox / radio
            elif act_type == "check":
                locator = _resolve_external_locator(page, field_id, selector)
                if await locator.count() > 0 and await locator.is_visible():
                    await locator.check(timeout=3000)

            # 6. Upload file
            elif act_type == "upload":
                target_path = action.get("path") or resume_path
                if os.path.exists(target_path):
                    file_input = page.locator("input[type='file']").first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(target_path)
                        print(f"  Uploaded file: {os.path.basename(target_path)}")
                        await asyncio.sleep(2)
                        await wait_for_processing_spinners(page)

            # 7. Dismiss broken auto-parsed card
            elif act_type == "dismiss_card":
                dismiss_btn = page.locator(selector).first if selector else page.locator(":text('Fields to fix') button").first
                if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                    await dismiss_btn.click()

            # 8. Click button
            elif act_type == "click":
                btn_text = action.get("text", "")
                btn = page.locator(f"button:has-text('{btn_text}'), input[type='submit'][value='{btn_text}']").first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=5000)
                    await asyncio.sleep(2)

        except Exception as e:
            print(f"  Action execution warning ({act_type}): {e}")


def _resolve_external_locator(page: Page, field_id: str, selector: str = "") -> Locator:
    """Helper to locate elements using ID, name, or custom selector."""
    if selector:
        return page.locator(selector).first
    if field_id:
        escaped = field_id.replace('"', '\\"')
        return page.locator(f'[id="{escaped}"], [name="{escaped}"], [data-automation-id="{escaped}"]').first
    return page.locator("body")


async def execute_external_portal_apply(
    page: Page, profile: dict[str, Any], job_title: str = "", max_pages: int = 10
) -> bool:
    """
    Main controller for Phase 2:
    - Navigates external company portals
    - Handles account creation/login gates
    - Employs the Per-Page Self-Healing Validation Loop across all pages until submission.
    """
    platform = detect_portal_platform(page.url)
    print(f"\n=======================================================")
    print(f"  [Phase 2] External Company Portal ({platform.upper()})")
    print(f"  Portal URL: {page.url}")
    print(f"=======================================================")

    # Step A: Handle Account Gate / Login if present
    await handle_portal_authentication_if_needed(page, profile)
    await asyncio.sleep(2)

    # Step B: Sense & Ensure we are on the actual job application form
    await sense_and_navigate_to_application(page, job_title)
    await asyncio.sleep(2)

    # Step C: Per-Page Loop with Self-Healing Error Resolution
    for page_idx in range(1, max_pages + 1):
        print(f"\n>>> [Phase 2] Processing Portal Page {page_idx}/{max_pages} <<<")

        page_result = await satisfy_current_page_and_advance(page, profile, max_healing_attempts=4)

        if page_result == "DONE":
            print("\n Application successfully submitted on external company portal!")
            return True
        elif page_result == "ADVANCED":
            print(f"  Page {page_idx} successfully satisfied and advanced.")
            await asyncio.sleep(2)
            continue
        elif page_result == "STUCK":
            print(f"  Could not satisfy conditions for Page {page_idx}. Checking if submission succeeded anyway...")
            if await is_external_submission_success(page):
                print("  Application submitted successfully!")
                return True
            return False

    return await is_external_submission_success(page)


async def is_external_submission_success(page: Page) -> bool:
    """Check if the external company portal has completed submission."""
    success_selectors = [
        ":text('Thank you for applying')",
        ":text('Application Submitted')",
        ":text('Your application has been received')",
        ":text('Submission Successful')",
        ":text('Congratulations')",
        ":text('Application complete')",
        "[data-automation-id='applicationConfirmation']",
        ".application-success",
    ]
    for sel in success_selectors:
        loc = page.locator(sel).first
        if await loc.count() > 0 and await loc.is_visible():
            return True
    return False
