/**
 * chat.js — AI Chat Panel
 * ========================
 * Calls the FastAPI /chat endpoint and displays responses.
 * Passes current map context (which district map is visible) to the AI.
 */

(function () {
  'use strict';

  const API_URL = window.FDGA_API_URL || '';  // empty = same origin (FastAPI serves both)

  const panel     = document.getElementById('chat-panel');
  const toggle    = document.getElementById('chat-toggle');
  const closeBtn  = document.getElementById('chat-close');
  const messages  = document.getElementById('chat-messages');
  const input     = document.getElementById('chat-input');
  const sendBtn   = document.getElementById('chat-send');
  const statusEl  = document.getElementById('chat-status');

  // ── Panel open/close ───────────────────────────────────────────────────────
  toggle.addEventListener('click', () => {
    panel.classList.toggle('hidden');
    if (!panel.classList.contains('hidden')) input.focus();
  });

  closeBtn.addEventListener('click', () => {
    panel.classList.add('hidden');
  });

  // ── Send message ──────────────────────────────────────────────────────────
  async function sendMessage() {
    const question = input.value.trim();
    if (!question) return;

    input.value = '';
    appendMessage('user', question);
    setStatus('Thinking…');
    sendBtn.disabled = true;

    // Include current map context so the AI knows what the user is looking at
    const ctx = window.FDGA && window.FDGA.getContext ? window.FDGA.getContext() : {};
    const fullQuestion = ctx.label
      ? `[User is viewing: ${ctx.label}] ${question}`
      : question;

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: fullQuestion, mode: 'auto' }),
      });

      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();

      appendMessage('ai', data.answer);

      if (data.chart_url) {
        appendChart(data.chart_url);
      }

      setStatus('');
    } catch (err) {
      appendMessage('ai', `Sorry, I couldn't reach the AI backend. Make sure the server is running.\n\n(${err.message})`);
      setStatus('');
    } finally {
      sendBtn.disabled = false;
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function appendMessage(role, text) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    // Convert newlines to <br> and basic markdown bold
    bubble.innerHTML = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');

    div.appendChild(bubble);
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function appendChart(chartUrl) {
    const div = document.createElement('div');
    div.className = 'msg ai';
    div.innerHTML = `<div class="msg-chart"><img src="${API_URL}${chartUrl}" alt="Chart" loading="lazy"></div>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function setStatus(msg) {
    statusEl.textContent = msg;
    statusEl.style.display = msg ? 'block' : 'none';
  }

})();
