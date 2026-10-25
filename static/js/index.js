let currentQuestion = 0;
let questions = [];
let score = 0;
let username = 'Player';
let selectedAnswer = null;
let levelRows = [];
let filteredLevelRows = [];
let currentPage = 1;
const pageSize = 25;
let appSettings = null;
let incorrectCards = [];
let incorrectCardIndex = 0;
let profilesCache = [];

const STORAGE_KEY = 'vocab_deck_profile';

function getUsername() {
    return document.getElementById('username-input').value || 'Player';
}

function goToPracticePage() {
    const name = getUsername();
    window.location.href = `/practice?username=${encodeURIComponent(name)}`;
}

// ──────────── Profile management ────────────

function setUsername(name) {
    username = name;
    document.getElementById('username-input').value = name;
    document.getElementById('profile-trigger-label').textContent = name;
    localStorage.setItem(STORAGE_KEY, name);
}

async function loadProfiles() {
    try {
        const resp = await fetch('/api/profiles');
        const data = await resp.json();
        profilesCache = data.profiles || [];
    } catch (_) {
        profilesCache = [];
    }
    renderProfileList();
}

function levelBarHtml(counts, total) {
    if (!total) return '';
    const colors = {
        master:        '#4caf50',
        proficient:    '#2196f3',
        practicing:    '#ff9800',
        'not-learned': '#e0e0e0',
    };
    const order = ['master', 'proficient', 'practicing', 'not-learned'];
    const segs = order.map(lvl => {
        const pct = ((counts[lvl] || 0) / total * 100).toFixed(1);
        return pct > 0
            ? `<div class="level-bar-seg" style="width:${pct}%;background:${colors[lvl]};" title="${lvl}: ${counts[lvl] || 0}"></div>`
            : '';
    }).join('');
    return `<div class="level-bar-wrap">${segs}</div>`;
}

function levelCountsHtml(counts) {
    const parts = [
        counts.master     ? `<span style="color:#4caf50;">&#9632; ${counts.master} master</span>`     : null,
        counts.proficient ? `<span style="color:#2196f3;">&#9632; ${counts.proficient} proficient</span>` : null,
        counts.practicing ? `<span style="color:#ff9800;">&#9632; ${counts.practicing} practicing</span>` : null,
    ].filter(Boolean);
    return parts.length ? parts.join(' &nbsp; ') : '<span style="color:#aaa;">No activity yet</span>';
}

function renderProfileList() {
    const list = document.getElementById('profile-list');
    list.innerHTML = '';
    if (!profilesCache.length) {
        list.innerHTML = '<div style="padding:10px 14px;color:#999;font-size:0.88em;">No profiles yet.</div>';
        return;
    }
    profilesCache.forEach(p => {
        const div = document.createElement('div');
        div.className = 'profile-option' + (p.username === username ? ' active' : '');
        div.innerHTML = `
            <div class="profile-name">👤 ${p.username}</div>
            <div class="profile-coverage">${p.coverage_pct}% covered &nbsp;·&nbsp; ${levelCountsHtml(p.level_counts)}</div>
            ${levelBarHtml(p.level_counts, p.total_vocab)}
        `;
        div.addEventListener('click', () => selectProfile(p.username));
        list.appendChild(div);
    });
}

function toggleProfileDropdown(e) {
    e && e.stopPropagation();
    const dd = document.getElementById('profile-dropdown');
    dd.classList.toggle('open');
    if (dd.classList.contains('open')) loadProfiles();
}

function closeProfileDropdown() {
    document.getElementById('profile-dropdown').classList.remove('open');
    document.getElementById('profile-new-input').classList.remove('open');
}

async function selectProfile(name) {
    setUsername(name);
    closeProfileDropdown();
    await refreshHomepage();
}

function showNewProfileInput() {
    const inp = document.getElementById('profile-new-input');
    inp.classList.add('open');
    document.getElementById('new-profile-name').focus();
}

async function createProfile() {
    const inp = document.getElementById('new-profile-name');
    const name = inp.value.trim();
    if (!name) return;
    inp.value = '';
    setUsername(name);
    closeProfileDropdown();
    await refreshHomepage();
}

document.addEventListener('click', (e) => {
    const wrap = document.getElementById('profile-selector-wrap');
    if (wrap && !wrap.contains(e.target)) closeProfileDropdown();
});

// ──────────── End profile management ────────────

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

async function fetchSettings() {
    const response = await fetch('/api/settings');
    const payload = await response.json();
    appSettings = payload.settings;
    return appSettings;
}

function fillSettingsForm(settings) {
    document.getElementById('cfg-practicing-limit').value = settings.practicing_limit;
    document.getElementById('cfg-daily-questions').value = settings.daily_questions;
    document.getElementById('cfg-min-prof').value = settings.min_attempts_proficient;
    document.getElementById('cfg-min-master').value = settings.min_attempts_master;
    document.getElementById('cfg-acc-prof').value = settings.proficient_accuracy_threshold;
    document.getElementById('cfg-acc-master').value = settings.master_accuracy_threshold;
    document.getElementById('cfg-pool-limit').value = settings.personalization_pool_limit;
    document.getElementById('cfg-lecture-words').value = settings.lecture_words;
    document.getElementById('cfg-carousel-size').value = settings.incorrect_carousel_size;
    document.getElementById('cfg-carousel-window').value = settings.incorrect_window_attempts;
    document.getElementById('cfg-carousel-syn').value = settings.carousel_synonyms_limit;
    document.getElementById('cfg-carousel-ant').value = settings.carousel_antonyms_limit;
}

function renderProjection(projection) {
    const prof = document.getElementById('projection-proficient');
    const master = document.getElementById('projection-master');
    prof.innerHTML = '';
    master.innerHTML = '';

    (projection.projections?.proficient || []).forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${item.target_percent}% (${item.target_words})</span><span>${item.eta_days} day(s)</span>`;
        prof.appendChild(li);
    });
    (projection.projections?.master || []).forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${item.target_percent}% (${item.target_words})</span><span>${item.eta_days} day(s)</span>`;
        master.appendChild(li);
    });
}

async function openSettingsMenu() {
    try {
        const settings = appSettings || await fetchSettings();
        fillSettingsForm(settings);
        const projectionResp = await fetch(`/api/projection/${encodeURIComponent(getUsername())}`);
        const projection = await projectionResp.json();
        renderProjection(projection);
        document.getElementById('settings-overlay').style.display = 'flex';
    } catch (error) {
        console.error('Error loading settings:', error);
        alert('Unable to load settings.');
    }
}

function closeSettingsMenu(event) {
    if (event && event.target && event.target.id !== 'settings-overlay') return;
    document.getElementById('settings-overlay').style.display = 'none';
}

async function saveSettings() {
    const payload = {
        practicing_limit: Number(document.getElementById('cfg-practicing-limit').value),
        daily_questions: Number(document.getElementById('cfg-daily-questions').value),
        min_attempts_proficient: Number(document.getElementById('cfg-min-prof').value),
        min_attempts_master: Number(document.getElementById('cfg-min-master').value),
        proficient_accuracy_threshold: Number(document.getElementById('cfg-acc-prof').value),
        master_accuracy_threshold: Number(document.getElementById('cfg-acc-master').value),
        personalization_pool_limit: Number(document.getElementById('cfg-pool-limit').value),
        lecture_words: Number(document.getElementById('cfg-lecture-words').value),
        incorrect_carousel_size: Number(document.getElementById('cfg-carousel-size').value),
        incorrect_window_attempts: Number(document.getElementById('cfg-carousel-window').value),
        carousel_synonyms_limit: Number(document.getElementById('cfg-carousel-syn').value),
        carousel_antonyms_limit: Number(document.getElementById('cfg-carousel-ant').value),
    };

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Failed to save settings');
        appSettings = result.settings;
        closeSettingsMenu();
        await refreshHomepage();
    } catch (error) {
        console.error('Error saving settings:', error);
        alert(error.message || 'Unable to save settings.');
    }
}

async function refreshHomepage() {
    username = getUsername();
    try {
        const response = await fetch(`/api/dashboard/${encodeURIComponent(username)}`);
        const data = await response.json();

        document.getElementById('today-score').textContent = `${data.results.today.score}/${data.results.today.total}`;
        document.getElementById('all-time-accuracy').textContent = `${data.results.all_time.accuracy}%`;
        document.getElementById('streak-current').textContent = data.streaks.current;
        document.getElementById('streak-best').textContent = data.streaks.best;
        document.getElementById('words-covered').textContent = data.word_coverage.words_covered;
        document.getElementById('total-vocab').textContent = data.word_coverage.total_vocab;
        document.getElementById('coverage-pct').textContent = `${data.word_coverage.coverage_pct}%`;

        const startBtn = document.getElementById('start-challenge-btn');
        if (data.active_challenge?.exists) {
            startBtn.textContent = `▶ Continue Challenge (${(data.active_challenge.current_index || 0) + 1}/${data.active_challenge.total_questions || 0})`;
        } else {
            startBtn.textContent = '▶ Start Challenge';
        }

        renderLatestExercises(data.latest_exercises);
        renderTrends(data.trends);
        renderLevelDictionary(data.level_dict);
        renderIncorrectCarousel(data.incorrect_carousel || []);
    } catch (error) {
        console.error('Error loading homepage data:', error);
        alert('Error loading homepage dashboard data.');
    }
}

function renderIncorrectCarousel(cards) {
    incorrectCards = cards || [];
    incorrectCardIndex = 0;
    renderIncorrectCarouselCard();
}

function moveIncorrectCarousel(delta) {
    if (!incorrectCards.length) return;
    incorrectCardIndex = (incorrectCardIndex + delta + incorrectCards.length) % incorrectCards.length;
    renderIncorrectCarouselCard();
}

function renderIncorrectCarouselCard() {
    const card = document.getElementById('incorrect-carousel-card');
    const index = document.getElementById('incorrect-carousel-index');

    if (!incorrectCards.length) {
        card.innerHTML = '<p>No incorrect words yet. Great start — keep practicing!</p>';
        index.textContent = '0 / 0';
        return;
    }

    const item = incorrectCards[incorrectCardIndex];
    const wordTypeBadge = item.word_type ? `<span class="word-type-badge">${item.word_type}</span>` : '';
    const senses = item.senses || [];
    let sensesHtml = '';
    if (senses.length) {
        sensesHtml = senses.map(sense => {
            const typeLabel = sense.word_type ? `<span class="word-type-badge">${sense.word_type}</span> ` : '';
            const synonyms = sense.synonyms?.length
                ? sense.synonyms.map(s => `<span class="word-chip">${wordLink(s, true)}</span>`).join('')
                : '<span class="word-chip">none</span>';
            const antonyms = sense.antonyms?.length
                ? sense.antonyms.map(a => `<span class="word-chip">${wordLink(a, true)}</span>`).join('')
                : '<span class="word-chip">none</span>';
            return `
                <div class="sense-block">
                    <p class="sense-def">${typeLabel}${sense.definition || 'Definition unavailable'}</p>
                    <div class="sense-label">Synonyms</div>
                    <div class="chip-row">${synonyms}</div>
                    <div class="sense-label" style="margin-top:6px;">Antonyms</div>
                    <div class="chip-row">${antonyms}</div>
                </div>
            `;
        }).join('');
    } else {
        sensesHtml = '<p>No sense data available.</p>';
    }

    card.innerHTML = `<div style="margin-bottom:4px;">${wordLink(item.word)}${wordTypeBadge}</div>${sensesHtml}`;
    index.textContent = `${incorrectCardIndex + 1} / ${incorrectCards.length}`;
}

function renderLatestExercises(items) {
    const list = document.getElementById('latest-exercises');
    list.innerHTML = '';
    if (!items || !items.length) {
        list.innerHTML = '<li><span>No exercises yet.</span><span class="tag">start challenge</span></li>';
        return;
    }
    items.forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `
            <div class="exercise-main">${wordLink(item.word)} <span class="tag">${item.challenge_type.replace('_match', '')}</span></div>
            <span class="exercise-status ${item.is_correct ? 'ok' : 'bad'}">${item.is_correct ? 'correct' : 'wrong'}</span>
        `;
        list.appendChild(li);
    });
}

function renderTrends(trends) {
    const list = document.getElementById('trend-list');
    list.innerHTML = '';
    if (!trends || !trends.length) {
        list.innerHTML = '<li><span>No trend data yet.</span><span class="tag">0%</span></li>';
        return;
    }
    trends.forEach(row => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${row.date}</span><span>${row.correct}/${row.answered} (${row.accuracy}%)</span>`;
        list.appendChild(li);
    });
}

function renderLevelDictionary(levelDict) {
    const entries = Object.entries(levelDict || {});
    levelRows = entries.map(([word, meta]) => ({ word, ...meta }));
    levelRows.sort((a, b) => {
        const levelRank = { 'practicing': 0, 'not-learned': 1, 'proficient': 2, 'master': 3 };
        return (levelRank[a.level] ?? 99) - (levelRank[b.level] ?? 99) || b.occurrences - a.occurrences || a.word.localeCompare(b.word);
    });
    currentPage = 1;
    applyLevelFilter();
}

function applyLevelFilter() {
    const selectedLevel = document.getElementById('level-filter').value;
    filteredLevelRows = selectedLevel === 'all' ? [...levelRows] : levelRows.filter(r => r.level === selectedLevel);
    currentPage = 1;
    renderLevelPage();
}

function changePage(delta) {
    const maxPage = Math.max(1, Math.ceil(filteredLevelRows.length / pageSize));
    currentPage = Math.min(maxPage, Math.max(1, currentPage + delta));
    renderLevelPage();
}

function renderLevelPage() {
    const body = document.getElementById('level-table-body');
    body.innerHTML = '';

    if (!filteredLevelRows.length) {
        const tr = document.createElement('tr');
        tr.innerHTML = '<td colspan="6">No words for the selected filter.</td>';
        body.appendChild(tr);
    } else {
        const start = (currentPage - 1) * pageSize;
        filteredLevelRows.slice(start, start + pageSize).forEach(row => {
            const tr = document.createElement('tr');
            const typeHtml = row.word_type
                ? `<span class="word-type-badge" style="margin-left:0;">${row.word_type}</span>`
                : '<span style="color:#bbb;">—</span>';
            tr.innerHTML = `
                <td>${wordLink(row.word)}</td>
                <td>${typeHtml}</td>
                <td>${row.occurrences}</td>
                <td>${row.correct}</td>
                <td>${row.accuracy}%</td>
                <td><span class="level-badge" style="background:${row.color};">${row.level}</span></td>
            `;
            body.appendChild(tr);
        });
    }

    const maxPage = Math.max(1, Math.ceil(filteredLevelRows.length / pageSize));
    document.getElementById('page-info').textContent = `Page ${currentPage} / ${maxPage}`;
    document.getElementById('dictionary-count').textContent = `${filteredLevelRows.length} words`;
    document.getElementById('prev-page-btn').disabled = currentPage <= 1;
    document.getElementById('next-page-btn').disabled = currentPage >= maxPage;
}

async function startChallenge() {
    username = getUsername();
    currentQuestion = 0;
    score = 0;
    selectedAnswer = null;

    document.getElementById('main-card').style.display = 'block';
    document.getElementById('homepage-grid').style.display = 'none';
    document.getElementById('loading').style.display = 'block';
    document.getElementById('lecture-container').style.display = 'none';
    document.getElementById('quiz-container').style.display = 'none';
    document.getElementById('results').style.display = 'none';

    try {
        const [lectureResp, challengeResp] = await Promise.all([
            fetch(`/api/lecture/${encodeURIComponent(username)}`),
            fetch(`/api/daily-challenge?username=${encodeURIComponent(username)}`),
        ]);
        const lectureData = await lectureResp.json();
        const challengeData = await challengeResp.json();

        questions = challengeData.questions;
        document.getElementById('loading').style.display = 'none';
        renderLecture(lectureData);
    } catch (error) {
        alert('Error loading challenge. Please make sure the server is running and data is available.');
        console.error(error);
    }
}

function renderLecture(lectureData) {
    const grid = document.getElementById('lecture-grid');
    const subtitle = document.getElementById('lecture-subtitle');
    grid.innerHTML = '';

    const cards = lectureData.cards || [];
    subtitle.textContent = `Review ${cards.length > 0 ? 'these ' + cards.length + ' words' : 'your vocabulary'} before starting your practice session`;

    if (!cards.length) {
        grid.innerHTML = '<p style="color:#999;text-align:center;grid-column:1/-1;">No lecture words available yet. Starting your practice now.</p>';
        setTimeout(beginPractice, 800);
        return;
    }

    cards.forEach(card => {
        const el = document.createElement('div');
        el.className = 'lecture-word-card';
        const wordTypeBadge = card.word_type ? `<span class="word-type-badge">${card.word_type}</span>` : '';
        const sensesHtml = (card.senses || []).map(sense => {
            const badge = sense.word_type && sense.word_type !== card.word_type
                ? `<span class="word-type-badge">${sense.word_type}</span> ` : '';
            const syns = (sense.synonyms || []).map(s =>
                `<span class="word-chip">${wordLink(s, true)}</span>`).join('');
            const ants = (sense.antonyms || []).map(a =>
                `<span class="word-chip">${wordLink(a, true)}</span>`).join('');
            return `
                <div class="sense-block">
                    <p class="sense-def">${badge}${sense.definition || ''}</p>
                    ${syns ? `<div class="sense-label">Synonyms</div><div class="chip-row">${syns}</div>` : ''}
                    ${ants ? `<div class="sense-label" style="margin-top:4px;">Antonyms</div><div class="chip-row">${ants}</div>` : ''}
                </div>`;
        }).join('');
        el.innerHTML = `
            <div class="lc-word-row">
                <span class="lc-word">${wordLink(card.word)}</span>
                ${wordTypeBadge}
            </div>
            ${sensesHtml || '<p style="color:#aaa;font-size:0.85em;">No definition available.</p>'}
        `;
        grid.appendChild(el);
    });

    document.getElementById('lecture-container').style.display = 'block';
}

function beginPractice() {
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

    document.getElementById('question-number').textContent = `Question ${currentQuestion + 1} of ${questions.length}`;
    const typeBadge = question.word_type ? `<span class="word-type-badge">${question.word_type}</span>` : '';
    document.getElementById('target-word').innerHTML = `${wordLink(question.word, true)} ${typeBadge}`;
    document.getElementById('question-text').textContent = question.question;
    document.getElementById('progress-fill').style.width = `${(currentQuestion / questions.length) * 100}%`;

    const choicesContainer = document.getElementById('choices');
    choicesContainer.innerHTML = '';
    question.choices.forEach(choice => {
        const btn = document.createElement('button');
        btn.className = 'choice-btn';
        btn.dataset.choice = choice;
        btn.innerHTML = `<span>${choice}</span> ${wordLookupIcon(choice)}`;
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

    try {
        const response = await fetch('/api/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ challenge: question, answer: selectedAnswer, username }),
        });
        const result = await response.json();
        if (result.correct) score++;

        const feedback = document.getElementById('feedback');
        feedback.className = `feedback show ${result.correct ? 'correct' : 'incorrect'}`;
        feedback.innerHTML = `<h3>${result.correct ? '✓ Correct!' : '✗ Incorrect'}</h3><p>${result.explanation}</p>`;

        document.querySelectorAll('.choice-btn').forEach(btn => {
            btn.disabled = true;
            if (btn.dataset.choice === question.correct_answer) btn.classList.add('correct');
            else if (btn.dataset.choice === selectedAnswer && !result.correct) btn.classList.add('incorrect');
        });

        document.getElementById('submit-btn').style.display = 'none';
        document.getElementById('next-btn').style.display = 'inline-block';

        await fetch('/api/update-progress', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, score: result.correct ? 1 : 0, total: 1 }),
        });
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

    const dashboardResp = await fetch(`/api/dashboard/${encodeURIComponent(username)}`);
    const dashboard = await dashboardResp.json();
    document.getElementById('result-streak').textContent = dashboard.streaks.current;
}

async function goHome() {
    document.getElementById('main-card').style.display = 'none';
    document.getElementById('homepage-grid').style.display = 'grid';
    await refreshHomepage();
}

document.getElementById('username-input').addEventListener('change', refreshHomepage);
const _savedProfile = localStorage.getItem(STORAGE_KEY);
if (_savedProfile) setUsername(_savedProfile);
fetchSettings().then(refreshHomepage).catch(() => refreshHomepage());
