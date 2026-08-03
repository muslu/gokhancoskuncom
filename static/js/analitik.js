/* GA4 baslatma.
 *
 * Neden ayri dosya: Google'in verdigi kod satir ici (<script>...</script>) gelir.
 * Satir ici script CSP'de ya 'unsafe-inline' ya da her degisiklikte guncellenmesi
 * gereken bir sha256 hash'i ister. Dosyaya alinca `script-src 'self'` yetiyor —
 * CSP gevsetilmiyor ve olcum kimligi degisince hash'i guncelleme derdi kalmiyor.
 *
 * Olcum kimligi HTML'den `data-ga-id` ile gelir; kimlik bossa sablon bu dosyayi
 * zaten yuklemez, yine de burada ikinci kez kontrol edilir.
 */
(function () {
  "use strict";

  // `defer` ile calistigimiz icin document.currentScript null olabilir.
  var etiket = document.currentScript || document.querySelector("script[data-ga-id]");
  var olcumKimligi = etiket && etiket.getAttribute("data-ga-id");
  if (!olcumKimligi) return;

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.gtag = gtag;

  gtag("js", new Date());
  gtag("config", olcumKimligi, {
    // IP'yi kisalt: KVKK/GDPR tarafinda olcum kimligini kisisel veriye
    // baglamayi zorlastirir, raporlarda kayip yaratmaz.
    anonymize_ip: true
  });
})();
