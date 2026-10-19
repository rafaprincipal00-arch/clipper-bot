# Plan 100 clips/dia (20/10/2026)

Punto de partida medido (top_clips 20/10): 98 posts con datos, 24% pasa de 1.000 vistas.
YouTube: 68 posts, media 761, 35% >=1k. TikTok: 30 posts, media 153, 0% >=1k.
Dinero real: Content Rewards lifetime $0.00 (3 aprobados, 19 pendientes, 14 rechazados), Vyro $0.00.

## Verdades que no cambian
- Ninguna plataforma garantiza 1.000 vistas. Los rewards pagan por vista SOLO por encima del
  minimo por post: Vyro 5.000 vistas/post (max $1.000/post), TJR/Lanah 10.000, Expedia 1.000,
  clipping.net paga al juntar 100.000 vistas de campana (cada clip debe pasar de 1.000).
- Con media actual de 750 (YT) / 153 (TT), un clip medio NO cobra. El plan es subir el hit-rate,
  no "cobrar cada mil vistas".
- TikTok: 3-5 posts/cuenta/dia sin spam. YouTube API: ~6 subidas/dia por proyecto (1.600 uds/subida).
  Instagram Graph: 50 posts API/dia por cuenta (realista 5-8). Una cuenta nueva la crea Rafa, nunca el bot.

## Fases
Fase 1 (ya, sin Rafa): 21/dia = 15 TikTok (5x3 cuentas) + 6 Shorts.
  - Arreglado: poster TikTok roto (greenlet/playwright) desde el 18/10 (82 fallos); ayer solo salieron 6-7.
  - Quota por datos: TJR, Lacy, N3on, Fanum, Ice Poseidon apagados (medias 1-180); el volumen va a
    Lanah/Spreen/Clix/Auronplay/Clix x Yeat/Stable Ronaldo/Kai Cenat + campanas Vyro.
  - performance.json ahora sobrevive al commit de Actions (bug arreglado): quota() 2x/1x funciona con datos.
  - Objetivo: 21/21 publicados/dia y >=35% de clips sobre 1k en 7 dias. Ingresos esperados: $0-2/dia.
Fase 2 (Rafa crea 3 TikTok nuevas + 3 IG Creator; ~1-2 semanas): ~50/dia = 30 TT (6 cuentas) + 6 YT + 15 IG.
  - IG Reels via Graph API (patron ya montado: video en GitHub release + Meta app).
  - Actions: 2 dispatches de clipper.yml (batch 25, ~3 h cada uno, repo publico = minutos gratis).
  - Ingresos esperados si el 35% >1k se mantiene y cae algun 5k-10k: $2-8/dia.
Fase 3 (100/dia; solo si fase 2 da >=30% >1k): 13-15 TikTok + 4-5 IG + 2-3 canales/proyectos YT.
  - 4-5 dispatches escalonados/dia (~6-7 h de runner, gratis en repo publico).
  - PC 6 GB: el poster TikTok local aguanta ~30-40 posts/dia espaciados (1 Chromium, picos 700 MB,
    gate de 900 MB libres); el resto debe ir por API (YT/IG, ligero). 100 posts locales NO caben.
  - Ingresos optimistas con 100/dia, media 800 y 30% en campana: $10-40/dia. Sin garantias.

## Lo que falta de Rafa (exacto)
1. Vyro > Settings > Payout methods > Connect an account (Stripe o PayPal). Sin esto no se cobra nada.
2. Vyro > Settings > Connected accounts > Connect an account > YouTube: loguearse con
   pepetiktok00.4@gmail.com para vincular @pepestreamclips (el bot no teclea contrasenas).
3. Fase 2: crear 3 cuentas TikTok y 3 Instagram Creator nuevas (el bot las vincula por QR).
