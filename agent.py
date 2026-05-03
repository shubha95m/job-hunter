import os
import json
import asyncio
from dotenv import load_dotenv
from llm_wrapper import generate_action

load_dotenv()

async def extract_form_context(page):
    """
    Extracts visible form fields, labels, and text from the modal.
    Returns a simplified JSON representation of the form.
    """
    # A smart way to extract form fields without guessing locators.
    # We use Playwright's evaluate_all to automatically pierce the shadow DOM.
    form_data = await page.locator(".artdeco-modal input, .artdeco-modal select, .artdeco-modal textarea, [role='dialog'] input, [role='dialog'] select, [role='dialog'] textarea").evaluate_all("""
    (elements) => {
        return elements.map(el => {
            // Try to find the label text
            let labelText = '';
            if (el.labels && el.labels.length > 0) {
                labelText = el.labels[0].innerText;
            } else {
                // Walk up the tree to find a nearby label or legend
                const container = el.closest('.jobs-easy-apply-form-section__grouping, div, fieldset');
                if (container) {
                    const labelEl = container.querySelector('label, legend, span');
                    if (labelEl) labelText = labelEl.innerText;
                }
            }
            
            // Check for validation errors
            let errorText = '';
            const container = el.closest('.jobs-easy-apply-form-section__grouping, div, fieldset');
            if (container) {
                const errorEl = container.querySelector('.artdeco-inline-feedback--error');
                if (errorEl) errorText = errorEl.innerText;
            }
            
            // Get options for select
            let options = [];
            if (el.tagName.toLowerCase() === 'select') {
                options = Array.from(el.options).map(o => o.text);
            }
            
            return {
                id: el.id,
                type: el.type || el.tagName.toLowerCase(),
                label: labelText.trim(),
                options: options,
                value: el.value,
                error: errorText.trim(),
                isVisible: el.offsetWidth > 0 && el.offsetHeight > 0
            };
        }).filter(item => item.isVisible && item.id);
    }
    """)
    
    # Extract visible buttons (like Next, Review, Submit)
    buttons = await page.locator(".artdeco-modal button, [role='dialog'] button").evaluate_all("""
    (elements) => {
        return elements.map(b => ({
            text: b.innerText.trim(),
            ariaLabel: b.getAttribute('aria-label'),
            isVisible: b.offsetWidth > 0 && b.offsetHeight > 0
        })).filter(b => b.isVisible && (b.text || b.ariaLabel));
    }
    """)
    
    return {"fields": form_data, "buttons": buttons}

async def decide_next_action(form_context, profile):
    """
    Asks the LLM Wrapper what to do next based on the form and profile.
    """
    prompt = f"""
You are an expert AI job application assistant. Your goal is to fill out a job application form on behalf of the user based on their profile.

USER PROFILE:
{json.dumps(profile, indent=2)}

CURRENT FORM STATE (Extracted from DOM):
{json.dumps(form_context, indent=2)}

INSTRUCTIONS:
1. Analyze the form fields. If there are fields that need to be filled, map them to the user's profile.
2. If there is a required field you don't know the answer to, make your best professional guess based on the profile context.
3. If the form looks complete or is just asking you to review a selected resume, your ONLY action should be to click the primary progression button.
4. You MUST end your action array with a click action for the primary progression button. The exact text must match one of the buttons in the CURRENT FORM STATE (e.g. 'Next', 'Review', 'Submit application').
5. CRITICAL: Look closely at the CURRENT FORM STATE. If any field has an 'error' property that is not empty, your previous answer was invalid or missing. You MUST provide a different, valid answer that satisfies the error message.

Respond ONLY with a JSON array of actions in this exact format, with no markdown formatting around it:
[
  {{"action": "fill", "id": "input_element_id", "value": "Text to type"}},
  {{"action": "select", "id": "select_element_id", "value": "Exact option text to select"}},
  {{"action": "click", "text": "Next"}} 
]
"""

    return await generate_action(prompt)

async def execute_smart_form_fill(page, profile):
    """
    The main loop that senses the page, asks AI, and acts until finished.
    """
    print("\n--- Starting Smart AI Form Filling ---")
    max_steps = 10
    
    for step in range(max_steps):
        print(f"Step {step + 1}: Sensing page context...")
        # Give the modal a second to render
        await asyncio.sleep(2)
        
        form_context = await extract_form_context(page)
        
        if not form_context["fields"] and not form_context["buttons"]:
            print("No visible form fields or buttons found. Assuming application is done or stuck.")
            break
            
        print("Asking AI for next actions...")
        actions = await decide_next_action(form_context, profile)
        
        if not actions:
            print("AI didn't return any actions. Stopping.")
            break
            
        print(f"AI suggested actions: {json.dumps(actions)}")
        
        # Execute actions
        for action in actions:
            try:
                if action["action"] == "fill":
                    print(f"-> Typing '{action['value']}' into #{action['id']}")
                    await page.locator(f"[id='{action['id']}']").fill(action['value'])
                elif action["action"] == "select":
                    print(f"-> Selecting '{action['value']}' in #{action['id']}")
                    # Use label since options is an array of text
                    await page.locator(f"[id='{action['id']}']").select_option(label=action['value'])
                elif action["action"] == "click":
                    print(f"-> Clicking button with text '{action['text']}'")
                    # Prioritize clicking inside the modal to avoid clicking background elements
                    btn = page.locator(f"[role='dialog'] button:has-text('{action['text']}'), [role='dialog'] button[aria-label='{action['text']}']").first
                    if await btn.count() == 0:
                        btn = page.locator(f"button:has-text('{action['text']}'), button[aria-label='{action['text']}']").first
                    await btn.click()
                    # Wait for the page to transition or show client-side errors
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"Error executing action {action}: {e}")
                
        # If the action was Submit, break the loop
        submit_clicked = any(a.get("action") == "click" and "submit" in a.get("text", "").lower() for a in actions)
        if submit_clicked:
            print("Submit clicked. Checking for errors...")
            await asyncio.sleep(3) # Wait for success screen or error
            
            # Smart Verification: Check if an error message appeared preventing submission
            error_text = page.locator(".artdeco-inline-feedback--error")
            if await error_text.count() > 0 and await error_text.first.is_visible():
                print("Error detected after submit. AI will attempt to fix.")
                continue # Loop again so AI can fix the error!
                
            print("Application complete!")
            return True
            
    print("--- Finished Form Filling ---\n")
    return False
