document.addEventListener('DOMContentLoaded', function () {
    const drawer = document.getElementById('chatbotDrawer');
    const overlay = document.getElementById('chatbotDrawerOverlay');
    const form = document.getElementById('chatbotForm');
    const input = document.getElementById('chatbotInput');
    const messages = document.getElementById('chatbotMessages');

    if (!drawer || !overlay || !form || !input || !messages) {
        return;
    }

    function appendMessage(text, type) {
        const bubble = document.createElement('div');
        bubble.className = 'chatbot-bubble ' + (type === 'user' ? 'chatbot-user-message' : 'chatbot-ai-message');
        bubble.textContent = text;
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
    }

    function setDrawerState(isOpen) {
        drawer.classList.toggle('is-open', isOpen);
        overlay.classList.toggle('is-visible', isOpen);
        drawer.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
        document.body.classList.toggle('chatbot-open', isOpen);

        if (isOpen) {
            window.setTimeout(function () {
                input.focus();
            }, 120);
        }
    }

    function openDrawer(prefillPrompt) {
        setDrawerState(true);
        if (prefillPrompt) {
            input.value = prefillPrompt;
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }
    }

    function closeDrawer() {
        setDrawerState(false);
    }

    document.querySelectorAll('[data-open-chat="true"]').forEach(function (trigger) {
        trigger.addEventListener('click', function () {
            const prompt = trigger.getAttribute('data-chat-prompt') || '';
            openDrawer(prompt);
        });
    });

    document.querySelectorAll('[data-close-chat="true"]').forEach(function (trigger) {
        trigger.addEventListener('click', function () {
            closeDrawer();
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && drawer.classList.contains('is-open')) {
            closeDrawer();
        }
    });

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        const question = input.value.trim();
        if (!question) {
            return;
        }

        appendMessage(question, 'user');
        input.value = '';

        const pending = document.createElement('div');
        pending.className = 'chatbot-bubble chatbot-ai-message chatbot-pending';
        pending.textContent = 'Analyzing your data...';
        messages.appendChild(pending);
        messages.scrollTop = messages.scrollHeight;

        try {
            const response = await fetch('/ai-chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ question: question }),
            });

            if (!response.ok) {
                throw new Error('Unable to get AI response');
            }

            const payload = await response.json();
            const source = payload.source === 'llm' ? 'AI model' : 'local analysis';
            pending.textContent = payload.answer + ' (' + source + ')';
            pending.classList.remove('chatbot-pending');
        } catch (error) {
            pending.textContent = 'I could not process that right now. Please try again in a few seconds.';
            pending.classList.remove('chatbot-pending');
        }
    });
});
