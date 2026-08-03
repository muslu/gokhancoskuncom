/* Site betikleri — defer ile yuklenir, sira korunur. */
(function () {
  "use strict";

  /* ---------- Tema gecisi ---------- */
  var dugme = document.getElementById("tema-dugme");
  if (dugme) {
    dugme.addEventListener("click", function () {
      var kok = document.documentElement;
      var suanki = kok.getAttribute("data-theme");
      if (!suanki) {
        // Henuz secim yok — sistem temasinin tersine gec
        suanki = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      var yeni = suanki === "dark" ? "light" : "dark";
      kok.setAttribute("data-theme", yeni);
      try {
        localStorage.setItem("gc-tema", yeni);
      } catch (e) { /* depolama kapali — tercih kalici olmaz */ }
      dugme.setAttribute(
        "aria-label",
        yeni === "dark" ? "Açık temaya geç" : "Koyu temaya geç"
      );
    });
  }

  /* ---------- Genis tablolari kaydirilabilir kutuya al ----------
     Markdown'dan gelen tablolar sayfa govdesini yatay kaydirmasin. */
  document.querySelectorAll(".icerik table").forEach(function (tablo) {
    if (tablo.parentElement && tablo.parentElement.classList.contains("kaydir")) return;
    var sarmal = document.createElement("div");
    sarmal.className = "kaydir";
    sarmal.setAttribute("tabindex", "0");
    sarmal.setAttribute("role", "region");
    sarmal.setAttribute("aria-label", "Kaydırılabilir tablo");
    tablo.parentNode.insertBefore(sarmal, tablo);
    sarmal.appendChild(tablo);
  });

  /* ---------- Yikici islemler icin onay ----------
     CSP `script-src 'self'` satir ici onsubmit'i bloklar; onay metni
     data-onay niteliginden okunur. */
  document.querySelectorAll("form[data-onay]").forEach(function (f) {
    f.addEventListener("submit", function (olay) {
      if (!window.confirm(f.getAttribute("data-onay"))) olay.preventDefault();
    });
  });

  /* ---------- Iletisim formu geri bildirimi ---------- */
  var form = document.getElementById("iletisim-form");
  if (form) {
    form.addEventListener("submit", function () {
      var gonder = form.querySelector('button[type="submit"]');
      if (gonder) {
        gonder.disabled = true;
        gonder.textContent = "Gönderiliyor…";
      }
    });
  }
})();
