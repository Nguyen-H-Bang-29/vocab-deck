let currentQuestion = 0;
let questions = [];
let score = 0;
let username = 'Player';
let selectedAnswer = null;
let sessionId = null;

// Lecture / SRS state
let lectureCards = [];
let lectureIndex = 0;

// GRE Reading Comprehension state
let rcQuestions = [];
let lastSessionWords = [];

function relationInfo(question) {
    const type = (question?.type || '').toLowerCase();
    const questionText = (question?.question || '').toLowerCase();
    if (type.includes('antonym') || questionText.includes('antonym')) {
        return { kind: 'antonym', label: 'ANTONYM', hint: 'Pick the word with the opposite meaning.' };
    }
    return { kind: 'synonym', label: 'SYNONYM', hint: 'Pick the word with the same or closest meaning.' };
}

function wordLink(word, compact = false) {
    const url = `https://www.merriam-webster.com/dictionary/${encodeURIComponent(word)}`;
    if (compact) {
        return `<a class="word-link" href="${url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();">${word}<span class="word-link-icon">↗</span></a>`;
    }
    return `<a class="word-link" href="${url}" target="_blank" rel="noopener noreferrer">${word}</a>`;
}

function wordLookupIcon(word) {
    const url = `https://www.merriam-webster.com/dictionary/${encodeURIComponent(word)}`;
    return `<a class="word-link word-link-icon" href="${url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();" title="Open Merriam-Webster definition">↗</a>`;
}

function getUsernameFromContext() {
    const qs = new URLSearchParams(window.location.search);
    const fromQuery = qs.get('username');
    const fromStorage = localStorage.getItem('vocab_deck_profile');
    return fromQuery || fromStorage || 'Player';
}

async function startPracticeFlow() {
    username = getUsernameFromContext();
    document.getElementById('profile-label').textContent = `Profile: ${username}`;
    currentQuestion = 0;
    score = 0;
    selectedAnswer = null;
    sessionId = null;

    document.getElementById('loading').style.display = 'block';
    document.getElementById('session-note').style.display = 'none';
    document.getElementById('lecture-container').style.display = 'none';
    document.getElementById('quiz-container').style.display = 'none';
    document.getElementById('results').style.display = 'none';

    try {
        const sessionResp = await fetch(`/api/practice-session/${encodeURIComponent(username)}`);
        const session = await sessionResp.json();

        sessionId = session.session_id;
        questions = session.questions || [];
        currentQuestion = session.current_index || 0;
        score = session.score || 0;

        renderLecture({ cards: session.lecture || [] });

        document.getElementById('loading').style.display = 'none';
        if (session.is_resumed && currentQuestion > 0) {
            const note = document.getElementById('session-note');
            note.textContent = `Resuming your in-progress challenge at question ${currentQuestion + 1} of ${questions.length}.`;
            note.style.display = 'block';
            beginPractice();
        } else {
            document.getElementById('lecture-container').style.display = 'block';
        }

        if (!questions.length) {
            document.getElementById('lecture-subtitle').textContent = 'No practice questions available right now.';
        }
    } catch (error) {
        alert('Error loading practice flow.');
        console.error(error);
    }
}

function renderLecture(lectureData) {
    lectureCards = lectureData.cards || [];
    lectureIndex = 0;

    if (!lectureCards.length) {
        document.getElementById('flashcard').style.display = 'none';
        document.getElementById('lc-count').textContent = '0';
        document.getElementById('lecture-complete').style.display = 'block';
        document.getElementById('lecture-card-counter').textContent = 'No words to review';
        return;
    }

    showFlashcard(0);
}

function showFlashcard(idx) {
    const card = lectureCards[idx];
    const total = lectureCards.length;

    document.getElementById('lecture-card-counter').textContent = `Card ${idx + 1} of ${total}`;
    document.getElementById('lecture-progress-fill').style.width = `${(idx / total) * 100}%`;

    document.getElementById('fc-word').innerHTML = wordLink(card.word);
    document.getElementById('fc-word-type').innerHTML = card.word_type
        ? `<span class="word-type-badge">${card.word_type}</span>` : '';

    document.getElementById('flashcard-front').style.display = '';
    document.getElementById('flashcard-back').style.display = 'none';
    document.getElementById('flashcard').style.display = '';
    document.getElementById('lecture-complete').style.display = 'none';
}

function revealCard() {
    const card = lectureCards[lectureIndex];
    document.getElementById('fc-word-mini').innerHTML =
        `${wordLink(card.word)}${card.word_type ? ` <span class="word-type-badge">${card.word_type}</span>` : ''}`;

    const sensesHtml = (card.senses || []).map(sense => {
        const badge = sense.word_type && sense.word_type !== card.word_type
            ? `<span class="word-type-badge">${sense.word_type}</span> ` : '';
        const syns = (sense.synonyms || []).map(s =>
            `<span class="word-chip word-chip-synonym">${wordLink(s, true)}</span>`).join('');
        const ants = (sense.antonyms || []).map(a =>
            `<span class="word-chip word-chip-antonym">${wordLink(a, true)}</span>`).join('');
        return `
            <div class="sense-block">
                <p class="sense-def">${badge}${sense.definition || ''}</p>
                ${syns ? `<div class="sense-label sense-label-synonym">Synonyms</div><div class="chip-row chip-row-synonym">${syns}</div>` : ''}
                ${ants ? `<div class="sense-label sense-label-antonym" style="margin-top:4px;">Antonyms</div><div class="chip-row chip-row-antonym">${ants}</div>` : ''}
            </div>`;
    }).join('');
    document.getElementById('fc-senses').innerHTML =
        sensesHtml || '<p style="color:#aaa;font-size:0.9em;">No definition available.</p>';

    document.getElementById('flashcard-front').style.display = 'none';
    document.getElementById('flashcard-back').style.display = '';
}

function rateCard(quality) {
    const card = lectureCards[lectureIndex];
    fetch('/api/srs/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, word: card.word, quality }),
    }).catch(() => {});

    lectureIndex++;
    if (lectureIndex < lectureCards.length) {
        showFlashcard(lectureIndex);
    } else {
        document.getElementById('flashcard').style.display = 'none';
        document.getElementById('lecture-progress-fill').style.width = '100%';
        document.getElementById('lecture-card-counter').textContent =
            `All ${lectureCards.length} cards reviewed`;
        document.getElementById('lc-count').textContent = lectureCards.length;
        document.getElementById('lecture-complete').style.display = 'block';
    }
}

function beginPractice() {
    if (!questions.length) return;
    document.getElementById('lecture-container').style.display = 'none';
    document.getElementById('quiz-container').style.display = 'block';
    displayQuestion();
}

function displayQuestion() {
    if (currentQuestion >= questions.length) {
        showResults();
        return;
    }

    const question = questions[currentQuestion];
    selectedAnswer = null;
    const relation = relationInfo(question);

    const typeBadge = question.word_type
        ? `<span class="word-type-badge">${question.word_type}</span>` : '';
    const relationPrompt = document.getElementById('relation-prompt');
    relationPrompt.className = `relation-prompt relation-${relation.kind}`;
    relationPrompt.textContent = `${relation.label}: ${relation.hint}`;
    document.getElementById('question-number').textContent = `Question ${currentQuestion + 1} of ${questions.length}`;
    document.getElementById('target-word').innerHTML = `${wordLink(question.word, true)} ${typeBadge}`;
    document.getElementById('question-text').textContent = question.question;
    document.getElementById('progress-fill').style.width = `${(currentQuestion / questions.length) * 100}%`;

    const choicesContainer = document.getElementById('choices');
    choicesContainer.innerHTML = '';
    question.choices.forEach((choice, idx) => {
        const btn = document.createElement('button');
        btn.className = 'choice-btn';
        btn.dataset.choice = choice;
        btn.innerHTML = `<span class="key-hint">${idx + 1}</span><span>${choice}</span>${wordLookupIcon(choice)}`;
        btn.onclick = () => selectChoice(choice, btn);
        choicesContainer.appendChild(btn);
    });

    document.getElementById('submit-btn').disabled = true;
    document.getElementById('submit-btn').style.display = 'inline-block';
    document.getElementById('next-btn').style.display = 'none';
    document.getElementById('feedback').classList.remove('show');
}

function selectChoice(answer, btn) {
    selectedAnswer = answer;
    document.querySelectorAll('.choice-btn').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');
    document.getElementById('submit-btn').disabled = false;
}

async function submitAnswer() {
    if (!selectedAnswer) return;

    const question = questions[currentQuestion];
    const relation = relationInfo(question);
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Checking…';

    try {
        const response = await fetch(`/api/practice-session/${sessionId}/answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                answer: selectedAnswer,
                username: username,
                question_index: currentQuestion,
            }),
        });

        const result = await response.json();
        score = result.score ?? (result.correct ? score + 1 : score);

        const feedback = document.getElementById('feedback');
        feedback.className = `feedback show ${result.correct ? 'correct' : 'incorrect'}`;
        feedback.innerHTML = `
            <h3>${result.correct ? '✓ Correct!' : '✗ Incorrect'}</h3>
            <p><strong>${relation.label} reminder:</strong> ${relation.hint}</p>
            <p>${result.explanation}</p>
        `;

        document.querySelectorAll('.choice-btn').forEach(btn => {
            btn.disabled = true;
            if (btn.dataset.choice === question.correct_answer) {
                btn.classList.add('correct');
            } else if (btn.dataset.choice === selectedAnswer && !result.correct) {
                btn.classList.add('incorrect');
            }
        });

        document.getElementById('submit-btn').style.display = 'none';
        document.getElementById('next-btn').style.display = 'inline-block';
    } catch (error) {
        alert('Error submitting answer');
        console.error(error);
    }
}

function nextQuestion() {
    currentQuestion++;
    displayQuestion();
}

async function showResults() {
    document.getElementById('quiz-container').style.display = 'none';
    document.getElementById('results').style.display = 'block';

    const accuracy = Math.round((score / questions.length) * 100);
    document.getElementById('final-score').textContent = `${score}/${questions.length}`;
    document.getElementById('result-correct').textContent = score;
    document.getElementById('result-accuracy').textContent = `${accuracy}%`;
    document.getElementById('result-streak').textContent = '…';

    lastSessionWords = [...new Set(questions.map(q => q.word))];
    // Kick off both in parallel; reading passage has its own loading UI
    const [dashboardResp] = await Promise.all([
        fetch(`/api/dashboard/${encodeURIComponent(username)}`),
        fetchReadingPassage(lastSessionWords),
    ]);
    const dashboard = await dashboardResp.json();
    document.getElementById('result-streak').textContent = dashboard.streaks.current;
}

function refreshReadingPassage() {
    if (!lastSessionWords.length) return;
    fetchReadingPassage(lastSessionWords, { regenerate: true });
}

async function fetchReadingPassage(words, { regenerate = false } = {}) {
    const section = document.getElementById('reading-passage-section');
    const loadingEl = document.getElementById('reading-loading');
    const refreshBtn = document.getElementById('reading-refresh-btn');
    section.style.display = 'block';
    loadingEl.style.display = 'block';
    loadingEl.innerHTML = `<div class="spinner"></div><p style="color:#888;font-size:0.9em;">Generating your reading exercise...</p>`;
    document.getElementById('reading-content').style.display = 'none';
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const resp = await fetch('/api/reading-passage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ words, username, regenerate }),
        });

        if (!resp.ok) {
            const errBody = await resp.json().catch(() => ({}));
            let reason = errBody.reason || errBody.error || `HTTP ${resp.status}`;
            if (errBody.error === 'rate_limited') {
                const secs = errBody.retry_after ?? 60;
                const reasonText = secs >= 60 ? `${Math.ceil(secs / 60)} min` : `${secs}s`;
                reason = `Generation limit reached. Try again in ${reasonText} (cached results are instant).`;
            }
            loadingEl.innerHTML = `<p style="color:#c0392b;font-size:0.9em;">Reading exercise unavailable: ${reason}</p>`;
            return;
        }

        const data = await resp.json();

        document.getElementById('reading-text').innerHTML = highlightWords(data.passage, data.words || words);
        document.getElementById('reading-words').innerHTML =
            (data.words || words).map(w => `<span class="word-chip reading-word-chip">${w}</span>`).join('');

        renderRCQuestions(data.questions || []);

        loadingEl.style.display = 'none';
        document.getElementById('reading-content').style.display = 'block';
    } catch (err) {
        console.error('Reading passage fetch failed:', err);
        loadingEl.innerHTML = `<p style="color:#c0392b;font-size:0.9em;">Reading exercise failed to load. Check console for details.</p>`;
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function renderRCQuestions(qs) {
    rcQuestions = qs;
    const container = document.getElementById('rc-questions');
    if (!qs.length) { container.innerHTML = ''; return; }

    container.innerHTML = `
        <div class="rc-divider"></div>
        <h4 class="rc-section-heading">Comprehension Questions</h4>
        ${qs.map((q, qi) => `
            <div class="rc-question" id="rc-q-${qi}">
                <p class="rc-question-text">${qi + 1}. ${q.question}</p>
                <div class="rc-choices">
                    ${q.choices.map((choice, ci) => `
                        <label class="rc-choice" id="rc-lbl-${qi}-${ci}">
                            <input type="radio" name="rc-q${qi}" value="${ci}" onchange="onRCChange()">
                            <span>${choice}</span>
                        </label>
                    `).join('')}
                </div>
                <div class="rc-explanation" id="rc-exp-${qi}" style="display:none;">
                    ${q.explanation}
                </div>
            </div>
        `).join('')}
        <div style="text-align:center;margin-top:18px;">
            <button class="btn btn-primary" id="rc-check-btn" onclick="checkRCAnswers()" disabled>
                Check Answers
            </button>
        </div>
    `;
}

function onRCChange() {
    const allAnswered = rcQuestions.every((_, i) =>
        document.querySelector(`input[name="rc-q${i}"]:checked`)
    );
    document.getElementById('rc-check-btn').disabled = !allAnswered;
}

function checkRCAnswers() {
    rcQuestions.forEach((q, qi) => {
        const checked = document.querySelector(`input[name="rc-q${qi}"]:checked`);
        const selected = checked ? parseInt(checked.value) : -1;
        const correct = q.correct_index;

        document.querySelectorAll(`input[name="rc-q${qi}"]`).forEach(radio => {
            radio.disabled = true;
            const ci = parseInt(radio.value);
            const lbl = document.getElementById(`rc-lbl-${qi}-${ci}`);
            if (ci === correct) lbl.classList.add('rc-correct');
            else if (ci === selected) lbl.classList.add('rc-incorrect');
        });

        document.getElementById(`rc-exp-${qi}`).style.display = 'block';
        document.getElementById(`rc-q-${qi}`).classList.add(
            selected === correct ? 'rc-answered-correct' : 'rc-answered-incorrect'
        );
    });

    const btn = document.getElementById('rc-check-btn');
    btn.disabled = true;
    btn.textContent = 'Answers Revealed';
}

function highlightWords(text, words) {
    // Sort longest first so "formless" is matched before "form" if both appear
    const sorted = [...words].sort((a, b) => b.length - a.length);
    let result = text;
    for (const word of sorted) {
        const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        result = result.replace(
            new RegExp(`\\b${escaped}\\b`, 'gi'),
            m => `<mark class="vocab-highlight">${m}</mark>`
        );
    }
    return result;
}

function goHome() {
    window.location.href = '/';
}

// Fly.io stops the machine after a few idle minutes (auto_stop_machines).
// A quiz session can go several minutes between requests (reading a passage,
// picking answers), so ping a cheap endpoint periodically to keep the
// machine warm and avoid a cold-start mid-session.
const KEEP_ALIVE_INTERVAL_MS = 4 * 60 * 1000;

function startKeepAlive() {
    setInterval(() => {
        fetch('/api/status').catch(() => {});
    }, KEEP_ALIVE_INTERVAL_MS);
}

document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    const quizVisible  = document.getElementById('quiz-container').style.display !== 'none';
    const lectureVisible = document.getElementById('lecture-container').style.display !== 'none';

    if (quizVisible) {
        const submitBtn = document.getElementById('submit-btn');
        const nextBtn   = document.getElementById('next-btn');

        if (['1', '2', '3', '4'].includes(e.key)) {
            const choices = document.querySelectorAll('.choice-btn:not([disabled])');
            const btn = choices[parseInt(e.key) - 1];
            if (btn) btn.click();
        } else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            if (nextBtn.style.display !== 'none') nextQuestion();
            else if (!submitBtn.disabled) submitAnswer();
        }
        return;
    }

    if (lectureVisible) {
        const flashcard = document.getElementById('flashcard');
        if (!flashcard || flashcard.style.display === 'none') return;

        const frontVisible = document.getElementById('flashcard-front').style.display !== 'none';
        const backVisible  = document.getElementById('flashcard-back').style.display  !== 'none';

        if (frontVisible && (e.key === ' ' || e.key === 'Enter')) {
            e.preventDefault();
            revealCard();
        } else if (backVisible) {
            if (e.key === '1') rateCard(1);
            else if (e.key === '2') rateCard(3);
            else if (e.key === '3') rateCard(4);
            else if (e.key === '4') rateCard(5);
        }
    }
});

startPracticeFlow();
startKeepAlive();
