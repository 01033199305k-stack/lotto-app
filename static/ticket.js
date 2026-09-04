// ---------- 실제로 산 용지 등록 (QR 스캔 / 번호 직접 입력) ----------
//
// 여기서 담은 게임은 기존 "내가 저장한 번호"와 같은 저장소에 들어간다.
// 그래야 추첨 후 등수 자동확인이 그대로 붙는다. 다만 회차는 targetRound()가 아니라
// 용지에 찍힌 회차를 쓴다 — 지난 회차 용지를 뒤늦게 등록할 수도 있으니까.

(function () {
  const modal = document.getElementById("ticket-modal");
  if (!modal) return;

  const openBtn = document.getElementById("ticket-open");
  const panes = {
    qr: document.getElementById("ticket-qr"),
    manual: document.getElementById("ticket-manual"),
  };
  const tabs = modal.querySelectorAll(".ticket-tab");

  const scanner = document.getElementById("ticket-scanner");
  const video = document.getElementById("ticket-video");
  const qrMsg = document.getElementById("ticket-qr-msg");
  const startBtn = document.getElementById("ticket-scan-start");
  const fileInput = document.getElementById("ticket-file-input");

  const roundInput = document.getElementById("ticket-round-input");
  const grid = document.getElementById("ticket-grid");
  const manualMsg = document.getElementById("ticket-manual-msg");
  const addGameBtn = document.getElementById("ticket-add-game");

  const basket = document.getElementById("ticket-basket");
  const basketList = document.getElementById("ticket-basket-list");
  const countEl = document.getElementById("ticket-count");
  const saveBtn = document.getElementById("ticket-save");

  let stream = null;
  let scanLoop = null;
  let detector = null;
  let jsqrLoading = null;
  let picked = [];
  let cart = [];

  // ---- 공용 ----

  function say(el, text, kind) {
    el.textContent = text;
    el.className = kind ? "ticket-msg " + kind : "ticket-msg";
  }

  function setMode(mode) {
    tabs.forEach((t) => t.classList.toggle("active", t.dataset.ticketMode === mode));
    panes.qr.hidden = mode !== "qr";
    panes.manual.hidden = mode !== "manual";
    if (mode !== "qr") stopScan();
  }

  function openModal() {
    modal.hidden = false;
    document.body.classList.add("modal-open");
    const next = typeof targetRound === "function" ? targetRound("lotto") : null;
    if (next && !roundInput.value) roundInput.value = next;
    setMode("qr");
    renderCart();
  }

  function closeModal() {
    stopScan();
    modal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  // ---- 담아둔 게임 ----

  function renderCart() {
    countEl.textContent = cart.length;
    basket.hidden = cart.length === 0;
    basketList.innerHTML = "";

    cart.forEach((game, i) => {
      const row = document.createElement("div");
      row.className = "ticket-cart-row";

      const round = document.createElement("span");
      round.className = "ticket-cart-round";
      round.textContent = game.round + "회";
      row.appendChild(round);

      const balls = document.createElement("div");
      balls.className = "ticket-cart-balls";
      game.numbers.forEach((n) => balls.appendChild(makeBall(n, colorRangeClass(n))));
      row.appendChild(balls);

      const del = document.createElement("button");
      del.type = "button";
      del.className = "saved-remove";
      del.textContent = "빼기";
      del.addEventListener("click", () => {
        cart.splice(i, 1);
        renderCart();
      });
      row.appendChild(del);

      basketList.appendChild(row);
    });
  }

  function addToCart(round, games) {
    let added = 0;
    let dup = 0;
    games.forEach((numbers) => {
      const key = numbers.join(",");
      if (cart.some((g) => g.round === round && g.numbers.join(",") === key)) {
        dup += 1;
        return;
      }
      cart.push({ round: round, numbers: numbers });
      added += 1;
    });
    renderCart();
    return { added: added, dup: dup };
  }

  // ---- QR 스캔 ----

  // BarcodeDetector는 안드로이드 크롬에만 있다. 아이폰 사파리는 jsQR로 대신한다.
  function loadJsQR() {
    if (window.jsQR) return Promise.resolve(window.jsQR);
    if (jsqrLoading) return jsqrLoading;
    jsqrLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/jsQR/1.4.0/jsQR.min.js";
      s.onload = () => resolve(window.jsQR);
      s.onerror = () => reject(new Error("QR 라이브러리를 불러오지 못했어요."));
      document.head.appendChild(s);
    });
    return jsqrLoading;
  }

  async function getDetector() {
    if (detector !== null) return detector;
    if ("BarcodeDetector" in window) {
      try {
        const formats = await window.BarcodeDetector.getSupportedFormats();
        if (formats.includes("qr_code")) {
          detector = new window.BarcodeDetector({ formats: ["qr_code"] });
          return detector;
        }
      } catch (e) {
        // jsQR로 넘어간다
      }
    }
    detector = false;
    return detector;
  }

  function frameToImageData(source, w, h) {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, w, h);
    return ctx.getImageData(0, 0, w, h);
  }

  async function readQRFrom(source, w, h) {
    const det = await getDetector();
    if (det) {
      const found = await det.detect(source);
      return found.length ? found[0].rawValue : null;
    }
    const jsQR = await loadJsQR();
    const img = frameToImageData(source, w, h);
    const found = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
    return found ? found.data : null;
  }

  function stopScan() {
    if (scanLoop) {
      clearInterval(scanLoop);
      scanLoop = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    scanner.hidden = true;
    startBtn.textContent = "카메라 켜기";
  }

  async function startScan() {
    if (stream) {
      stopScan();
      say(qrMsg, "용지 아래쪽 QR코드를 카메라에 비춰주세요.");
      return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      say(qrMsg, "이 브라우저는 카메라를 지원하지 않아요. '사진에서 찾기'를 써주세요.", "warn");
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
    } catch (e) {
      const denied = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
      say(
        qrMsg,
        denied
          ? "카메라 권한이 거부됐어요. 주소창 자물쇠에서 허용하거나 '사진에서 찾기'를 써주세요."
          : "카메라를 열지 못했어요. '사진에서 찾기'를 써주세요.",
        "warn"
      );
      return;
    }

    video.srcObject = stream;
    try {
      await video.play();
    } catch (e) {
      // 자동재생이 막혀도 프레임은 읽히는 경우가 있어 계속 진행한다
    }
    scanner.hidden = false;
    startBtn.textContent = "카메라 끄기";
    say(qrMsg, "QR을 찾는 중...");

    scanLoop = setInterval(async () => {
      if (!video.videoWidth) return;
      let raw = null;
      try {
        raw = await readQRFrom(video, video.videoWidth, video.videoHeight);
      } catch (e) {
        return;
      }
      if (!raw) return;
      stopScan();
      submitQR(raw);
    }, 350);
  }

  async function scanFile(file) {
    say(qrMsg, "사진에서 QR을 찾는 중...");
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const raw = await readQRFrom(img, img.naturalWidth, img.naturalHeight);
      if (!raw) {
        say(qrMsg, "사진에서 QR을 찾지 못했어요. 좀 더 가깝게 찍어보세요.", "warn");
        return;
      }
      submitQR(raw);
    } catch (e) {
      say(qrMsg, e.message || "사진을 읽지 못했어요.", "warn");
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function submitQR(raw) {
    say(qrMsg, "번호를 읽는 중...");
    try {
      const res = await fetch("/api/ticket/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: raw }),
      });
      const data = await res.json();

      if (!data.ok) {
        say(qrMsg, data.error || "QR을 해석하지 못했어요.", "warn");
        return;
      }

      const res2 = addToCart(data.round, data.games);
      const parts = [data.round + "회차 " + data.games.length + "게임을 읽었어요."];
      if (res2.dup) parts.push(res2.dup + "게임은 이미 담겨 있어 건너뛰었어요.");
      if (res2.added) {
        // 지난 회차 용지면 저장하자마자 등수가 뜨니 미리 알려준다.
        parts.push(data.drawn ? "저장하면 바로 등수를 확인해드려요." : "아래에서 확인하고 저장하세요.");
      }
      say(qrMsg, parts.join(" "), res2.added ? "ok" : "warn");
    } catch (e) {
      say(qrMsg, "서버와 통신하지 못했어요.", "warn");
    }
  }

  // ---- 번호 직접 입력 ----

  function buildGrid() {
    for (let n = 1; n <= 45; n += 1) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ticket-cell";
      b.textContent = n;
      b.dataset.num = n;
      b.addEventListener("click", () => toggleNum(n, b));
      grid.appendChild(b);
    }
  }

  function toggleNum(n, btn) {
    const at = picked.indexOf(n);
    if (at >= 0) {
      picked.splice(at, 1);
      btn.classList.remove("on");
    } else {
      if (picked.length >= 6) {
        say(manualMsg, "6개까지만 고를 수 있어요. 하나 빼고 다시 골라주세요.", "warn");
        return;
      }
      picked.push(n);
      btn.classList.add("on");
    }
    addGameBtn.disabled = picked.length !== 6;
    say(
      manualMsg,
      picked.length === 6
        ? "다 골랐어요. '이 게임 담기'를 눌러주세요."
        : 6 - picked.length + "개 더 고르세요."
    );
  }

  function clearPicked() {
    picked = [];
    grid.querySelectorAll(".on").forEach((el) => el.classList.remove("on"));
    addGameBtn.disabled = true;
  }

  addGameBtn.addEventListener("click", () => {
    const round = parseInt(roundInput.value, 10);
    if (!Number.isInteger(round) || round < 1) {
      say(manualMsg, "회차를 입력해주세요.", "warn");
      return;
    }
    const sorted = picked.slice().sort((a, b) => a - b);
    const res = addToCart(round, [sorted]);
    clearPicked();
    say(
      manualMsg,
      res.added ? "담았어요. 계속 추가하거나 저장하세요." : "이미 담긴 게임이에요.",
      res.added ? "ok" : "warn"
    );
  });

  // ---- 저장 ----

  saveBtn.addEventListener("click", () => {
    if (!cart.length) return;
    let saved = 0;
    let skipped = 0;
    cart.forEach((game) => {
      if (saveTicketGame(game.round, game.numbers)) saved += 1;
      else skipped += 1;
    });

    cart = [];
    renderCart();
    closeModal();

    if (typeof showToast === "function") {
      showToast(
        skipped
          ? saved + "게임 저장했어요 (" + skipped + "게임은 이미 있었어요)"
          : saved + "게임 저장했어요. 추첨 후 등수를 자동으로 알려드려요"
      );
    }
    if (typeof renderSaved === "function") renderSaved("lotto");
  });

  // ---- 이벤트 배선 ----

  openBtn.addEventListener("click", openModal);
  modal.querySelectorAll("[data-ticket-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
  });
  tabs.forEach((t) => t.addEventListener("click", () => setMode(t.dataset.ticketMode)));
  startBtn.addEventListener("click", startScan);
  fileInput.addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) scanFile(f);
    e.target.value = "";
  });

  buildGrid();
})();
