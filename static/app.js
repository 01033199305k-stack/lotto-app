const gamesEl = document.getElementById("games");
const drawBtn = document.getElementById("draw-btn");
const statsChart = document.getElementById("stats-chart");
const strategyBtns = document.querySelectorAll(".strategy-btn");
const countBtns = document.querySelectorAll(".count-btn");
const historyList = document.getElementById("history-list");
const clearHistoryBtn = document.getElementById("clear-history");
const toast = document.getElementById("toast");
const excludeGrid = document.getElementById("exclude-grid");
const checkInputsEl = document.getElementById("check-inputs");
const checkBtn = document.getElementById("check-btn");
const checkResults = document.getElementById("check-results");

const STRATEGY_LABEL = {
  reliability: "신뢰도",
  frequency: "빈도",
  mixed: "혼합",
  random: "무작위",
};

const HISTORY_KEY = "lotto_draw_history";
const HISTORY_LIMIT = 30;
const EXCLUDE_KEY = "lotto_exclude_numbers";

let currentStrategy = "reliability";
let currentCount = 1;
let excludedNumbers = new Set();

function colorRangeClass(num) {
  if (num <= 10) return "range-1";
  if (num <= 20) return "range-2";
  if (num <= 30) return "range-3";
  if (num <= 40) return "range-4";
  return "range-5";
}

function makeBall(num, extraClass) {
  const ball = document.createElement("div");
  ball.className = `ball ${extraClass || ""}`.trim();
  ball.textContent = num;
  return ball;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 1600);
}

function copyGame(numbers) {
  const text = numbers.join(", ");
  navigator.clipboard
    .writeText(text)
    .then(() => showToast(`복사됨: ${text}`))
    .catch(() => showToast("복사에 실패했어요"));
}

function buildGameRow(index) {
  const row = document.createElement("div");
  row.className = "game-row";

  const top = document.createElement("div");
  top.className = "game-row-top";
  top.innerHTML = `<span class="game-label">GAME ${index + 1}</span>`;

  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-btn";
  copyBtn.type = "button";
  copyBtn.textContent = "복사";
  top.appendChild(copyBtn);

  const balls = document.createElement("div");
  balls.className = "balls";
  for (let i = 0; i < 6; i++) {
    balls.appendChild(makeBall("?", "placeholder"));
  }

  const meta = document.createElement("div");
  meta.className = "game-meta";

  row.appendChild(top);
  row.appendChild(balls);
  row.appendChild(meta);

  return { row, balls, meta, copyBtn };
}

function animateGame(ballsEl, finalNumbers, onDone, delay) {
  const ballEls = Array.from(ballsEl.children);
  ballEls.forEach((el) => {
    el.classList.remove("placeholder");
    el.classList.add("rolling");
  });

  const rollTimer = setInterval(() => {
    ballEls.forEach((el) => {
      el.textContent = 1 + Math.floor(Math.random() * 45);
    });
  }, 60);

  setTimeout(() => {
    clearInterval(rollTimer);
    ballEls.forEach((el, i) => {
      setTimeout(() => {
        el.classList.remove("rolling");
        el.classList.add("settled");
        el.className = `ball settled ${colorRangeClass(finalNumbers[i])}`;
        el.textContent = finalNumbers[i];
      }, i * 80);
    });
    setTimeout(onDone, 6 * 80 + 100);
  }, delay);
}

function renderMeta(metaEl, game) {
  metaEl.innerHTML = `
    <span>합계 ${game.sum}</span>
    <span>홀${game.odd} 짝${game.even}</span>
    <span>저${game.low} 고${game.high}</span>
  `;
}

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
  } catch {
    return [];
  }
}

function saveHistory(entries) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_LIMIT)));
}

function renderHistory() {
  const entries = loadHistory();
  historyList.innerHTML = "";

  if (entries.length === 0) {
    historyList.innerHTML = '<p class="history-empty">아직 뽑은 기록이 없어요.</p>';
    return;
  }

  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "history-item";

    const tag = document.createElement("span");
    tag.className = "history-tag";
    tag.textContent = `${STRATEGY_LABEL[entry.strategy] || entry.strategy}`;

    const ballsWrap = document.createElement("span");
    ballsWrap.className = "history-balls";
    entry.numbers.forEach((num) => {
      ballsWrap.appendChild(makeBall(num, colorRangeClass(num)));
    });

    item.appendChild(tag);
    item.appendChild(ballsWrap);
    historyList.appendChild(item);
  });
}

function addToHistory(strategy, games) {
  const entries = loadHistory();
  games.forEach((game) => {
    entries.unshift({ strategy, numbers: game.numbers, ts: Date.now() });
  });
  saveHistory(entries);
  renderHistory();
}

async function draw() {
  drawBtn.disabled = true;
  drawBtn.textContent = "뽑는 중...";
  gamesEl.innerHTML = "";

  const rows = [];
  for (let i = 0; i < currentCount; i++) {
    const built = buildGameRow(i);
    gamesEl.appendChild(built.row);
    rows.push(built);
  }

  try {
    const excludeParam = Array.from(excludedNumbers).join(",");
    const res = await fetch(
      `/api/draw/${currentStrategy}?count=${currentCount}&exclude=${excludeParam}`
    );
    const data = await res.json();

    let remaining = data.games.length;
    data.games.forEach((game, i) => {
      rows[i].copyBtn.addEventListener("click", () => copyGame(game.numbers));
      animateGame(
        rows[i].balls,
        game.numbers,
        () => {
          renderMeta(rows[i].meta, game);
          remaining -= 1;
          if (remaining === 0) {
            addToHistory(data.strategy, data.games);
            drawBtn.disabled = false;
            drawBtn.textContent = "번호 뽑기";
          }
        },
        300 + i * 150
      );
    });
  } catch (e) {
    drawBtn.disabled = false;
    drawBtn.textContent = "번호 뽑기";
    showToast("오류가 발생했어요");
  }
}

async function loadStats() {
  const res = await fetch("/api/stats");
  const data = await res.json();
  statsChart.innerHTML = "";
  data.top.forEach((item) => {
    const row = document.createElement("div");
    row.className = "stat-row";
    row.innerHTML = `
      <span>${item.number}</span>
      <span class="stat-bar-track"><span class="stat-bar-fill" style="width:${item.score}%"></span></span>
      <span>${item.score}</span>
    `;
    statsChart.appendChild(row);
  });
}

function loadExcluded() {
  try {
    return new Set(JSON.parse(localStorage.getItem(EXCLUDE_KEY)) || []);
  } catch {
    return new Set();
  }
}

function saveExcluded() {
  localStorage.setItem(EXCLUDE_KEY, JSON.stringify(Array.from(excludedNumbers)));
}

function buildExcludeGrid() {
  excludeGrid.innerHTML = "";
  for (let num = 1; num <= 45; num++) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "exclude-num";
    btn.textContent = num;
    if (excludedNumbers.has(num)) btn.classList.add("selected");
    btn.addEventListener("click", () => {
      if (excludedNumbers.has(num)) {
        excludedNumbers.delete(num);
        btn.classList.remove("selected");
      } else {
        if (excludedNumbers.size >= 39) {
          showToast("최소 6개는 남겨둬야 해요");
          return;
        }
        excludedNumbers.add(num);
        btn.classList.add("selected");
      }
      saveExcluded();
    });
    excludeGrid.appendChild(btn);
  }
}

function rankLabel(matchCount, bonusMatch) {
  if (matchCount === 6) return "1등";
  if (matchCount === 5 && bonusMatch) return "2등";
  if (matchCount === 5) return "3등";
  if (matchCount === 4) return "4등";
  if (matchCount === 3) return "5등";
  return "낙첨";
}

function runCheck() {
  const inputs = Array.from(checkInputsEl.querySelectorAll(".check-num:not(.check-bonus)"));
  const bonusInput = checkInputsEl.querySelector(".check-bonus");

  const winNumbers = inputs
    .map((el) => parseInt(el.value, 10))
    .filter((n) => Number.isInteger(n) && n >= 1 && n <= 45);

  if (winNumbers.length !== 6 || new Set(winNumbers).size !== 6) {
    showToast("1~45 사이 서로 다른 6개 번호를 입력해주세요");
    return;
  }

  const bonus = parseInt(bonusInput.value, 10);
  const winSet = new Set(winNumbers);
  const entries = loadHistory();

  if (entries.length === 0) {
    checkResults.innerHTML = '<p class="check-empty">대조할 히스토리가 없어요. 먼저 번호를 뽑아보세요.</p>';
    return;
  }

  const scored = entries.map((entry) => {
    const matched = entry.numbers.filter((n) => winSet.has(n));
    const bonusMatch = Number.isInteger(bonus) && entry.numbers.includes(bonus);
    return { entry, matched, matchCount: matched.length, bonusMatch };
  });

  scored.sort((a, b) => b.matchCount - a.matchCount);

  checkResults.innerHTML = "";
  scored.slice(0, 10).forEach(({ entry, matched, matchCount, bonusMatch }) => {
    const row = document.createElement("div");
    row.className = "check-row";

    const rank = document.createElement("span");
    const label = rankLabel(matchCount, bonusMatch);
    rank.className = `check-rank ${matchCount >= 3 ? "hit" : ""}`;
    rank.textContent = `${label} (${matchCount}개)`;

    const ballsWrap = document.createElement("span");
    ballsWrap.className = "check-balls";
    entry.numbers.forEach((num) => {
      const ball = makeBall(num, colorRangeClass(num));
      if (winSet.has(num)) ball.classList.add("matched");
      ballsWrap.appendChild(ball);
    });

    row.appendChild(rank);
    row.appendChild(ballsWrap);
    checkResults.appendChild(row);
  });
}

strategyBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    strategyBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentStrategy = btn.dataset.strategy;
  });
});

countBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    countBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentCount = parseInt(btn.dataset.count, 10);
  });
});

clearHistoryBtn.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
});

drawBtn.addEventListener("click", draw);
checkBtn.addEventListener("click", runCheck);

excludedNumbers = loadExcluded();
buildExcludeGrid();

loadStats();
renderHistory();

// initial placeholder row
const initial = buildGameRow(0);
gamesEl.appendChild(initial.row);
