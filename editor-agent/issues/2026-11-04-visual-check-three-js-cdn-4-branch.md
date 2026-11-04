# [editor-agent] visual check ล้มเพราะโหลด three.js จาก CDN ไม่ได้ (ข้อมูลรอบ 4 พ.ย. อยู่บน branch)

visual_check.py ล้มเหลว 16 error ในรอบ 2026-11-04 ทั้งหมดเป็น `request failed: https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js` / `net::ERR_CERT_AUTHORITY_INVALID` และ "globe did not render" — sandbox โหลด CDN ไม่ได้ ไม่เกี่ยวกับข้อมูล (check.py OK, pytest 162 passed, e2e 0 fail)
ผลคือ publish ขึ้น main ไม่ได้ จึงพุชไปที่ branch agent/2026-11-04-data-blocked
ข้อเสนอ: ให้ vendor three.js ในรีโป หรือให้ visual_check ข้ามข้อผิดพลาด CDN ในสภาพแวดล้อมที่ไม่มีเครือข่าย และ merge branch ดังกล่าวหากเห็นว่าข้อมูลถูกต้อง
