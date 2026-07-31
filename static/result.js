const gameTabs = document.querySelectorAll(".result-tabs .game-tab");
const roundInput = document.getElementById("round-input");
const roundPrev = document.getElementById("round-prev");
const roundNext = document.getElementById("round-next");
const searchBtn = document.getElementById("round-search");
const resultBox = document.getElementById("result-box");
const toast = document.getElementById("toast");

let currentGame = "lotto";
let latestRound = { lotto: null, pension: null };

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 1600);
}

function colorRangeClass(num) {
  if (num <= 10) return "range-1";
  if (num <= 20) return "range-2";
  if (num <= 30) return "range-3";
  if (num <= 40) return "range-4";
  return "range-5";
}

function makeBall(num, extraClass) {
  const el = document.createElement("div");
  el.className = `ball ${extraClass || ""}`.trim();
  el.textContent = num;
  return el;
}

function makeDigit(digit) {
  const el = document.createElement("div");
  el.className = "digit";
  el.textContent = digit;
  return el;
}

function makeGroupBadge(group) {
  const el = document.createElement("div");
  el.className = "group-badge";
  el.innerHTML = `${group}<span class="group-label">조</span>`;
  return el;
}

// 1,595,129,563 -> "15억 9,512만원" — 원 단위까지 읽어봐야 감이 안 오니 줄여서 쓴다.
function formatMoney(won) {
  if (won == null) return "-";
  if (won >= 100000000) {
    const eok = Math.floor(won / 100000000);
    const man = Math.floor((won % 100000000) / 10000);
    return man > 0 ? `${eok}억 ${man.toLocaleString()}만원` : `${eok}억원`;
  }
  if (won >= 10000) {
    return `${Math.floor(won / 10000).toLocaleString()}만원`;
  }
  return `${won.toLocaleString()}원`;
}

function renderLotto(r) {
  const balls = document.createElement("div");
  balls.className = "result-balls";
  r.numbers.forEach((n) => balls.appendChild(makeBall(n, colorRangeClass(n))));
  const plus = document.createElement("span");
  plus.className = "latest-plus";
  plus.textContent = "+";
  balls.appendChild(plus);
  balls.appendChild(makeBall(r.bonus, `${colorRangeClass(r.bonus)} bonus`));
  resultBox.appendChild(balls);

  if (!r.prizes) return;

  const table = document.createElement("table");
  table.className = "prize-table";
  table.innerHTML = `
    <thead><tr><th>등수</th><th>당첨자</th><th>1인당 당첨금</th></tr></thead>
    <tbody>
      ${r.prizes
        .map(
          (p) => `<tr>
            <td>${p.rank}등</td>
            <td>${p.winners != null ? p.winners.toLocaleString() + "명" : "-"}</td>
            <td>${formatMoney(p.amount)}</td>
          </tr>`
        )
        .join("")}
    </tbody>
  `;
  resultBox.appendChild(table);

  if (r.sales != null) {
    const sales = document.createElement("p");
    sales.className = "result-note";
    sales.textContent = `총 판매금액 ${formatMoney(r.sales)}`;
    resultBox.appendChild(sales);
  }
}

function renderPension(r) {
  const wrap = document.createElement("div");
  wrap.className = "result-balls";
  wrap.appendChild(makeGroupBadge(r.group));
  r.number.split("").forEach((d) => wrap.appendChild(makeDigit(d)));
  resultBox.appendChild(wrap);

  const bonus = document.createElement("p");
  bonus.className = "result-note";
  bonus.textContent = `보너스 번호 ${r.bonus}`;
  resultBox.appendChild(bonus);
}

async function loadRound(round) {
  if (!Number.isInteger(round) || round < 1) {
    showToast("조회할 회차를 입력해주세요");
    return;
  }

  searchBtn.disabled = true;
  searchBtn.textContent = "조회 중...";
  resultBox.innerHTML = "";

  try {
    const res = await fetch(`/api/result/${currentGame}/${round}`);
    const data = await res.json();

    if (!data.ok || !data.result) {
      resultBox.innerHTML =
        '<p class="result-empty">해당 회차 결과를 찾을 수 없어요. 아직 추첨 전이거나 없는 회차일 수 있습니다.</p>';
      return;
    }

    const r = data.result;
    roundInput.value = r.round;

    const head = document.createElement("p");
    head.className = "result-head";
    head.textContent = `제${r.round}회 (${r.date})`;
    resultBox.appendChild(head);

    if (currentGame === "lotto") renderLotto(r);
    else renderPension(r);
  } catch (e) {
    resultBox.innerHTML = '<p class="result-empty">조회 중 오류가 발생했어요.</p>';
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = "조회하기";
  }
}

function stepRound(delta) {
  const current = parseInt(roundInput.value, 10);
  if (!Number.isInteger(current)) return;
  const next = current + delta;
  if (next < 1) return;
  const max = latestRound[currentGame];
  if (max && next > max) {
    showToast("아직 추첨하지 않은 회차예요");
    return;
  }
  roundInput.value = next;
  loadRound(next);
}

async function initGame(game) {
  currentGame = game;
  resultBox.innerHTML = "";
  roundInput.value = "";

  try {
    const res = await fetch(`/api/latest/${game}`);
    const data = await res.json();
    if (data.ok && data.result) {
      latestRound[game] = data.result.round;
      roundInput.max = data.result.round;
      roundInput.value = data.result.round;
      loadRound(data.result.round);
      return;
    }
  } catch (e) {
    // fall through to the manual-entry hint below
  }

  resultBox.innerHTML = '<p class="result-empty">회차 번호를 입력하고 조회해보세요.</p>';
}

gameTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    gameTabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    initGame(tab.dataset.game);
  });
});

searchBtn.addEventListener("click", () => loadRound(parseInt(roundInput.value, 10)));
roundInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadRound(parseInt(roundInput.value, 10));
});
roundPrev.addEventListener("click", () => stepRound(-1));
roundNext.addEventListener("click", () => stepRound(1));

initGame("lotto");
