# ผู้ช่วยบรรณาธิการ (editor agent)

ผู้ช่วยบรรณาธิการคือ agent ของ Claude Managed Agents ที่ตื่นมาทำงานวันละครั้ง ตอน 07:00 น. เวลากรุงเทพฯ
เพื่อทำให้ข้อมูลพื้นฐานของหน้าเว็บ <https://zyser007.github.io/global-analysis/> ทันสมัย
ส่วนที่บอตของ GitHub Actions ดูแลอยู่แล้ว (ราคา 13 รายการและภัยพิบัติทุกชั่วโมงจากแหล่งข้อมูลฟรีโดยตรง ข่าววันละ 2 รอบด้วย Claude) ยังทำงานเหมือนเดิม ผู้ช่วยไม่แตะ

## ทำอะไรในแต่ละรอบ

1. อ่านความจำของตัวเอง (memory store) บันทึกรอบก่อน ปัญหาที่รู้อยู่ และเรื่องที่รอเจ้าของตัดสินใจ
2. ตรวจสุขภาพข้อมูลสด: `site/data/status.json`, อายุของไฟล์ราคา/ข่าว/ภัยพิบัติ, commit ของบอตใน 26 ชม., `updater/cost-log.csv`, ค่าที่ดูผิดปกติ
3. ดูภาพรวมทีละบรรทัดด้วย `brief.py` แล้วค้นข่าว 24 ชม. ล่าสุดเป็นชุด ๆ ครอบคลุมทุกความขัดแย้งระดับ 3 ขึ้นไป ช่องแคบระดับ 3 เศรษฐกิจที่มีตัวเลขใหม่ และทองคำ
   (ค้นเว็บไม่เกิน 24 ครั้ง เปิดหน้าเว็บไม่เกิน 12 หน้า เขียน patch ทันทีหลังค้นแต่ละชุดแล้วไม่ย้อนอ่านผลค้นเดิม) อ่านทีละรายการด้วย `show.py` ไม่แตะตัวชี้วัดที่หน้าเว็บแสดงสดจาก `market.json` (brief.py ทำเครื่องหมาย LIVE)
   แหล่งที่มาต้องเป็นหน่วยงานทางการ สำนักข่าวหลัก หรือองค์กรวิจัยเฉพาะทาง ห้ามบล็อก Substack เว็บรวมข่าวตลาด และหน้ากราฟ/หน้าราคา
   และต้องเผยแพร่ไม่เกิน 7 วันก่อนวันที่รัน (`apply_changes.py` และ `check.py` ปฏิเสธเอง)
4. แก้ข้อมูลผ่าน `apply_changes.py` เท่านั้น (patch เล็ก ๆ ทีละชุด) เครื่องมือนี้ตรวจก่อนเขียน ใส่แหล่งที่มาให้ และบันทึก URL กับวันที่ลง `editor-agent/runs/<วันที่>.changes.json`
   แล้วเขียนสรุปภาษาไทยไว้ใน `editor-agent/runs/<วันที่>.md`
5. `verify.sh` สร้างหน้าเว็บใหม่แล้วตรวจ `check.py`, `pytest`, `visual_check.py` (1–3 นาที) พิมพ์แค่บทสรุปสั้น ๆ (`e2e/` รันเฉพาะเมื่อสั่ง `--e2e` ไม่ขวางการเผยแพร่)
6. ผ่าน → `publish.sh main` commit แล้ว push เข้า `main` (GitHub Pages เผยแพร่เองเพราะไฟล์ใน `site/` เปลี่ยน)
   ไม่ผ่าน → `publish.sh branch` push สำเนาเข้ากิ่ง `agent/<วันที่>-<หัวข้อ>` (ไฟล์ที่แก้ค้างไว้ไม่หาย) แล้วแจ้งผ่าน `issue.py` ไม่แตะ `main`
7. ไม่มีผู้ตรวจ rubric แล้ว (`verify.sh` + `check.py` คือด่านตรวจ) ไฟล์หลักฐานสำหรับเจ้าของอยู่ใน `/mnt/session/outputs/`: `live.txt`, `verify.txt`, `check.txt`, `publish.txt`, `issues.txt`, `summary.md` และไฟล์ของรอบ

agent ห้ามพิมพ์ไฟล์ข้อมูลทั้งไฟล์ ห้ามอ่านโค้ดหรือชุดทดสอบ ห้ามใช้ `git stash` / `reset` / `checkout -- ไฟล์`
ถ้าเครื่องมือหรือชุดทดสอบผิด ให้แจ้งเป็น issue แล้วทำส่วนที่ผ่านต่อ (บทเรียนจากรอบทดลองแรก ดูหัวข้อค่าใช้จ่าย)
7. เขียนบันทึกรอบลงความจำ แล้วสรุปผลเป็นภาษาไทย

ขอบเขตที่ห้ามเกิน (เขียนไว้ใน system prompt และ `check.py --scope` ตรวจซ้ำ): บน `main` แก้ได้เฉพาะ `data/world-data.json`, `data/gold.json`,
`site/index.html` ที่สร้างใหม่ และไฟล์ใน `editor-agent/runs/` ห้ามแก้ workflow, secret, โค้ด updater, ชุดทดสอบ ห้าม force-push ห้ามลบประวัติ

## ไฟล์ในโฟลเดอร์นี้

| ไฟล์ | หน้าที่ |
|---|---|
| `agent/agent.json`, `agent/system_prompt.md` | นิยาม agent: โมเดล `claude-sonnet-5-5` ระดับ effort `medium`, ชุดเครื่องมือ (bash, ไฟล์, web_search, web_fetch), คำสั่งงาน |
| `brief.py`, `show.py` | ภาพรวมข้อมูลบรรทัดละรายการ (~8–11 KB) และดูทีละรายการ แทนการเปิดไฟล์ข้อมูลทั้งไฟล์ (~90 KB) |
| `apply_changes.py`, `datatools.py` | แก้ข้อมูลด้วย patch: รักษารูปแบบไฟล์ ตรวจก่อนเขียน ใส่แหล่งที่มา และเขียน `runs/<วันที่>.changes.json` ให้เอง |
| `verify.sh`, `publish.sh` | ตรวจทั้งหมดแบบสรุปสั้น, commit + push อย่างปลอดภัย (rebase เมื่อชนกับบอต ไม่ force; โหมด branch ไม่แตะไฟล์ที่กำลังแก้) |
| `issue.py`, `open_issues.py`, `.github/workflows/agent-issues.yml` | agent เรียก REST API ของ GitHub จากกล่องไม่ได้ (proxy ไม่ใส่ token ให้) จึงเขียน issue เป็นไฟล์ในกิ่ง `agent/<วันที่>-issues` แล้ว workflow เปิดเป็น issue จริงด้วย `GITHUB_TOKEN` (ป้าย `editor-agent` ไม่ซ้ำ ไฟล์ที่แก้กลายเป็นความเห็น) |
| `environment.json` | กล่องทำงานบนคลาวด์ (Ubuntu มี Python, Node, Playwright + Chromium ติดมาแล้ว) และแพ็กเกจ pip ที่ลงเพิ่ม |
| `memory_store.json`, `memory_seed/` | ความจำข้ามรอบ และไฟล์ตั้งต้นที่ใส่ไว้ตอนสร้าง |
| `deployment.json`, `kickoff/` | ตารางเวลา 07:00 กรุงเทพฯ, เพดาน 3 ดอลลาร์ต่อรอบ, ข้อความเริ่มงาน (ข้อความธรรมดา ไม่มี outcome/rubric) และ `run-checklist.md` รายการตรวจสำหรับคน |
| `lock.json` | รหัสของ agent / environment / memory store / deployment ที่สร้างแล้ว (ไม่มีความลับ ควร commit) |
| `setup.py` | สร้างหรืออัปเดตวัตถุทั้งหมดจากไฟล์ข้างบน แล้วจดรหัสลง `lock.json` ไม่ลบหรือ archive อะไรเลย |
| `run_once.py` | สั่งรันทดลอง 1 รอบและดูความคืบหน้า, ดูรายการรอบที่ผ่านมา, ตอบคำขออนุญาตที่ค้าง |
| `check.py`, `schema/` | ตรวจรูปแบบข้อมูลด้วย JSON Schema, วันที่ไม่ล้าหลัง, ชื่อเรื่องไม่มีเดือน, ทุกจุดที่เปลี่ยนมีแหล่งที่มา, ขอบเขตไฟล์, สุขภาพข้อมูลสด |
| `visual_check.py` | เปิดหน้าเว็บจริงแบบไม่มีหน้าต่าง (มุมมองลูกโลก 4 ขนาด และโหมดอ่านง่าย 1 กรณีบนมือถือ) หา error, แผงว่าง, วันที่ไม่ตรง, ล้นจอ (ค่าที่คาดหวังอ่านจากข้อมูล ไม่ฝังตายตัว) |
| `e2e.sh` | รันชุดทดสอบ `e2e/` ในกล่องของ agent โดยใช้ Chromium ที่ติดมากับกล่อง |
| `tests/` | ทดสอบ `check.py`, เครื่องมือ และนิยามต่าง ๆ (ไม่ใช้เน็ต ใช้ข้อมูลแช่แข็งใน `tests/fixtures/` จึงไม่ล้มเพราะข้อมูลจริงเปลี่ยน): `.venv/bin/python -m pytest editor-agent/tests -q` |
| `runs/` | บันทึกแต่ละรอบที่ agent commit มา |

## ตั้งค่าครั้งแรก

ทุกคำสั่งรันจากโฟลเดอร์ repo และอ่านคีย์จากไฟล์ตอนรัน (ไม่พิมพ์คีย์ออกจอ):

```bash
K=/Users/zyser/Documents/work/key/global_analysis
ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py            # ดูแผนก่อน
ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py --apply    # สร้าง/อัปเดต agent, environment, memory store
```

agent, environment และ memory store สร้างไว้แล้ว (ดูรหัสใน `lock.json`) ขั้นที่เหลือ:

1. **สร้าง GitHub token แบบ fine-grained** (GitHub → Settings → Developer settings → Fine-grained tokens)
   - Repository access: เฉพาะ `zyser007/global-analysis`
   - Permissions: **Contents: Read and write**, **Issues: Read and write**, **Actions: Read-only**, Metadata: Read-only (บังคับอยู่แล้ว)
   - ห้ามให้ Workflows, Administration, Secrets, Pull requests (ไม่ให้ Workflows ทำให้ push ไฟล์ใน `.github/workflows/` ไม่ได้อยู่แล้ว เป็นด่านกันพลาดชั้นที่สอง)
   - อายุ 90 วัน แล้วบันทึกลงไฟล์ `/Users/zyser/Documents/work/key/github_agent_token` (บรรทัดเดียว) `chmod 600` ไฟล์นั้น
   token ไม่เข้าไปในกล่องของ agent: git proxy ของ Anthropic ใส่ให้ตอนคำขอออกจากกล่อง
2. **(แนะนำ) ตั้งกฎกันพลาดของกิ่ง `main`** (Settings → Rules → Rulesets): ห้าม force push และห้ามลบกิ่ง (ไม่บังคับ PR เพราะบอตและ agent push ตรง)
3. **ทดลองรัน 1 รอบ** (มีค่าใช้จ่าย ไม่เกิน 3 ดอลลาร์):
   ```bash
   ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/run_once.py session
   ```
   สคริปต์ถามยืนยัน พิมพ์ลิงก์ Console แสดงทุกขั้น (ค้นอะไร เปิดหน้าไหน รันคำสั่งอะไร) และค่าใช้จ่ายสุดท้าย
4. **เปิดตารางเวลา** เมื่อรอบทดลองผ่าน:
   ```bash
   ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py --apply --deployment
   ```
   จะเริ่มรันทุกวัน 07:00 น. (อาจช้าได้ถึง 9 นาที) ทดลองสั่งรอบของ deployment ทันที: `run_once.py deployment-run`

เปลี่ยน prompt / ข้อความเริ่มงาน / ตารางเวลา: แก้ไฟล์แล้วรัน `setup.py --apply` (เพิ่ม `--deployment` ถ้าแก้ `deployment.json` หรือ `kickoff/`)
agent จะได้เวอร์ชันใหม่ รอบถัดไปใช้เวอร์ชันล่าสุดเอง เปลี่ยน token แล้ว: `setup.py --apply --deployment --refresh-token`

## ค่าใช้จ่าย

แต่ละรอบเป็น 1 session คิดเงิน 3 ส่วน:

- **โทเค็น** Claude Sonnet 5.5: อินพุต 2 ดอลลาร์ต่อล้าน, เอาต์พุต 10, เขียนแคช 2.50, อ่านแคช 0.10 (ประวัติการทำงานถูกแคชให้อัตโนมัติ)
- **ค้นเว็บ** 10 ดอลลาร์ต่อ 1,000 ครั้ง (30 ครั้ง = 0.30 ดอลลาร์) เปิดหน้าเว็บด้วย web_fetch ไม่คิดต่อครั้ง จ่ายเฉพาะโทเค็นของเนื้อหา (จำกัดหน้าละ 6,000 โทเค็น)
- **เวลาที่ session ทำงาน** 0.08 ดอลลาร์ต่อชั่วโมง (รอบละราว 30–60 นาที ≈ 0.04–0.08)

รอบทดลองแรก (4 พ.ย. 2569) ใช้ครบเพดาน 3.01 ดอลลาร์ใน 10.5 นาทีโดยยังไม่ได้ push: อ่านแคช 7.6 ล้านโทเค็น (0.76), เขียนแคช 0.49 ล้าน (1.23),
เอาต์พุต 72,500 (0.73), ค้นเว็บ 28 ครั้ง (0.28) สาเหตุคือ agent พิมพ์ไฟล์ข้อมูลทั้งไฟล์และอ่านโค้ด/ชุดทดสอบ บริบทโตถึง ~190,000 โทเค็น
และทุกคำขอต่อมาต้องอ่านบริบทนั้นซ้ำ จึงแก้โดย: effort `medium`, เครื่องมือที่พิมพ์ผลสั้น (`brief.py` ~3,000 โทเค็นแทนไฟล์ข้อมูล ~30,000),
แก้ข้อมูลด้วย `apply_changes.py`, ตรวจด้วย `verify.sh` ที่พิมพ์ไม่ถึง 1 KB, ห้ามอ่านโค้ด และจำกัดค้นเว็บ 30 / เปิดหน้า 15
รอบทดลองที่สาม (ค้น 28 ครั้ง ครอบคลุม 22 รายการ) ใช้ครบ 3 ดอลลาร์เพราะผู้ตรวจ rubric สั่งแก้รอบที่สองหลังงานเสร็จ (อ่านแคช 10.8 ล้านโทเค็น)
จึงตัดผู้ตรวจออก เริ่มรอบด้วยข้อความธรรมดา จำกัดค้นเว็บ 24 ครั้ง และสั่งไม่ให้ย้อนอ่านผลค้นเดิม เป้าหมาย: ไม่เกิน 2.00 ดอลลาร์ต่อรอบ
เพดานแข็งรอบละ **3.00 ดอลลาร์** (ถึงเพดานแล้วหยุดรอ ไม่ทำงานต่อ) จึงไม่เกินราว 93 ดอลลาร์ต่อเดือน รวมกับบอตข่าว (~15–25 ดอลลาร์ต่อเดือน ตั้งแต่ราคาย้ายไปดึงตรงจากแหล่งข้อมูลฟรีซึ่งไม่มีค่าใช้จ่าย)
ให้ปรับวงเงินรายเดือนใน Console (Settings → Limits) ให้พอ ดูตัวเลขจริงด้วย `run_once.py runs` หรือหน้า session ใน Console
การสร้าง agent / environment / memory store / deployment ไม่มีค่าใช้จ่าย

## หยุดชั่วคราว / เปิดใหม่ / ฉุกเฉิน

```bash
ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py --pause     # หยุดตารางเวลา (รอบที่กำลังรันยังทำต่อ)
ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py --unpause   # เปิดอีกครั้ง (ไม่ย้อนรันรอบที่พลาด)
```

หรือใน Console หน้า Deployments กด Pause ถ้าต้องหยุดทันทีทุกอย่าง: ลบ (revoke) GitHub token ที่ GitHub
อย่าใช้ archive กับ agent / environment / deployment ถ้าแค่อยากหยุด เพราะ archive ย้อนกลับไม่ได้

## ดูการทำงาน

- Console: <https://platform.claude.com> → Managed Agents → **Sessions** (บันทึกทุกขั้น ค่าใช้จ่าย ไฟล์ใน outputs) และ **Deployments** (ตารางเวลา รอบที่รันแล้ว)
  ลิงก์ตรงของรอบหนึ่ง: `https://platform.claude.com/workspaces/default/sessions/<session id>`
  ถ้าคีย์อยู่ใน workspace อื่นที่ไม่ใช่ Default ให้แก้ `console_workspace` ใน `lock.json` เป็นรหัส workspace นั้น
- เครื่องตัวเอง: `run_once.py runs` (รายการรอบ สถานะ ค่าใช้จ่าย), `run_once.py follow <session id>` (ดูย้อนหลังหรือดูสด ไม่มีค่าใช้จ่ายเพิ่ม)
- GitHub: commit `chore(editor): ...`, กิ่ง `agent/*`, issue ป้าย `editor-agent`, และไฟล์ `editor-agent/runs/<วันที่>.md`

ถ้ารอบใดค้างอยู่ที่ "รออนุญาต" (เครื่องมือบางคำสั่งที่ระบบตัดสินเองไม่ได้ และไม่มีคนเฝ้า) จะเห็นใน Console เป็น idle / requires_action
ตอบด้วย `run_once.py pending <session id>` (ปฏิเสธ เป็นค่าเริ่มต้น) หรือ `--allow` ถ้าดูแล้วปลอดภัย

## ทำไมเครือข่ายเป็น `unrestricted`

ถ้าตั้งเป็น `limited` รายชื่อโฮสต์ที่อนุญาตจะจำกัด web_search / web_fetch ด้วย (ผลค้นจากเว็บนอกรายการจะหายไป)
งานนี้ต้องอ่านข่าวจากสำนักข่าวและหน่วยงานทั่วโลกที่ระบุล่วงหน้าไม่ได้ จึงเลือก `unrestricted`
ความเสี่ยงที่เหลือคือเนื้อหาจากเว็บพยายามสั่ง agent ซึ่งลดด้วย: ไม่มีความลับในกล่องเลย (token อยู่ที่ proxy), token มีสิทธิ์แค่ repo นี้และไม่มีสิทธิ์ Workflows,
system prompt ถือเนื้อหาเว็บเป็นข้อมูลไม่ใช่คำสั่ง, การอนุญาตเครื่องมือแบบ `auto` ปฏิเสธคำสั่งเสี่ยงสูงเอง และ `check.py --scope` ขวางไฟล์นอกขอบเขตก่อน push

## ข้อจำกัดที่รู้อยู่

- ชุดทดสอบ `e2e/` ใช้ข้อมูลพื้นฐานแช่แข็งใน `e2e/fixtures/` (`e2e/serve.py` ฝังแทนข้อมูลจริง) ข้อมูลรายวันจึงไม่ทำให้ e2e ล้ม ส่วน `visual_check.py` ตรวจหน้าเว็บกับข้อมูลวันนั้น
- issue จริงเปิดโดย workflow `agent-issues.yml` ซึ่งทำงานได้ก็ต่อเมื่อไฟล์ workflow อยู่บน `main` แล้ว (กิ่ง issue สร้างจาก `main`)
  กิ่ง `agent/2026-11-04-issues` ที่รอบทดลองที่สองสร้างไว้ก่อนมี workflow จะไม่ถูกเปิดเป็น issue เอง ให้เปิดด้วยมือหรือ push ไฟล์ใหม่ทับ
- ในกล่องของ agent การเชื่อมต่อ TLS ถูกเซ็นใหม่ Chromium จึงไม่เชื่อใบรับรองของเว็บภายนอก (cdnjs, Google Fonts):
  `visual_check.py` และ `e2e.sh` ข้ามข้อผิดพลาดใบรับรองเฉพาะในกล่อง แต่ error ในหน้า console error และคำขอไปยังเซิร์ฟเวอร์ทดสอบที่ล้มเหลวยังทำให้ตกเหมือนเดิม และทุกบรรทัดบอก URL
- `e2e.sh` ในกล่องยังไม่ได้ยืนยันกับ `@playwright/test` 1.56.1 (ถ้าใช้ Chromium ไม่ได้จะออกรหัส 3) และไม่อยู่ในรอบตรวจปกติ
