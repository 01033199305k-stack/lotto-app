// The CSS rule on ins.adsbygoogle[data-ad-status="unfilled"] covers slots
// AdSense explicitly reports back on. It does not cover a request that fails
// quietly: the <ins> keeps the height AdSense reserved for it but never gets a
// status, leaving an empty block in the page. Sweep those once, late enough
// that a slow-but-real ad has had time to land.
setTimeout(() => {
  document.querySelectorAll("ins.adsbygoogle").forEach((el) => {
    if (el.getAttribute("data-ad-status") !== "filled") {
      el.style.display = "none";
    }
  });
}, 8000);
