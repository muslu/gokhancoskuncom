---
name: ssh-mcp-takilmasi
description: excopan-ssh-web MCP oturumu calisirken olur ve her komut 120 sn'de timeout'a duser
metadata:
  type: reference
---

> Not: MCP sunucusunun tanimi ve baglanti bilgileri `.mcp.json`'da (git'e girmez).

`excopan-ssh-web` SSH MCP sunucusu oturum ortasinda yanit vermez hale gelebiliyor.
2026-08-03'te yasandi: birkac basarili komuttan sonra **`echo merhaba` bile**
120 sn'de `MCP error -32603: Command execution timed out` ile dustu. Komuta
`timeout 20` eklemek de fayda etmedi — takilan komut degil, **SSH oturumunun kendisi**.

**Belirti:** Arka arkaya butun `exec` cagrilari 120 sn timeout ile basarisiz;
komutun icerigi fark etmiyor.

**Cozum:** MCP sunucusunu yeniden baglamak gerekiyor (`/mcp`) — Claude tarafindan
duzeltilemiyor, kullanici mudahalesi sart.

**Onlem:** Uzun surebilecek uzak komutlari (curl ile disa acilan istekler, `su - postgres`)
tek tek ve kisa tut; toplu `&&` zincirleri takilmayi tetikliyor gorunuyor.
Ozellikle sunucunun **kendi public alan adina** curl atmasi (hairpin NAT) askida kalabiliyor —
onun yerine `127.0.0.1:8002` uzerinden test et.

Ilgili: [[deploy-durumu]]
