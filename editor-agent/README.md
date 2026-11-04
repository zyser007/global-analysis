# ผู้ช่วยบรรณาธิการ (editor agent)

ผู้ช่วยบรรณาธิการคือ agent ของ Claude Managed Agents ที่ตื่นมาทำงานวันละครั้ง ตอน 07:00 น. เวลากรุงเทพฯ
เพื่อทำให้ข้อมูลพื้นฐานของหน้าเว็บ <https://zyser007.github.io/global-analysis/> ทันสมัย
ส่วนที่บอตของ GitHub Actions ดูแลอยู่แล้ว (ราคา 13 รายการ ข่าว ภัยพิบัติ ทุก 4 ชม.) ยังทำงานเหมือนเดิม ผู้ช่วยไม่แตะ

## ทำอะไรในแต่ละรอบ

1. อ่านความจำของตัวเอง (memory store) บันทึกรอบก่อน ปัญหาที่รู้อยู่ และเรื่องที่รอเจ้าของตัดสินใจ
2. ตรวจสุขภาพข้อมูลสด: `site/data/status.json`, อายุของไฟล์ราคา/ข่าว/ภัยพิบัติ, commit ของบอตใน 26 ชม., `updater/cost-log.csv`, ค่าที่ดูผิดปกติ
3. ค้นข่าว 24 ชม. ล่าสุดของทุกความขัดแย้ง เศรษฐกิจ ช่องแคบ ตัวชี้วัด และแนวโน้มทองคำ (ค้นเว็บไม่เกิน 40 ครั้ง เปิดหน้าเว็บไม่เกิน 25 หน้า)
4. แก้ `data/world-data.json` และ `data/gold.json` ทุกข้อเท็จจริงที่เปลี่ยนต้องมี URL และวันที่ของแหล่งที่มา บันทึกไว้ใน `editor-agent/runs/<วันที่>.changes.json`
   และเขียนสรุปภาษาไทยไว้ใน `editor-agent/runs/<วันที่>.md`
5. สร้างหน้าเว็บใหม่ (`tools/splice_gold.py` + `tools/build.py`) แล้วตรวจ: `check.py`, `pytest`, `visual_check.py` (เปิดหน้าเว็บแบบไม่มีหน้าต่าง 4 แบบ) และชุดทดสอบ `e2e/`
6. ผ่านหมด → commit ไฟล์ข้อมูล หน้าเว็บ และบันทึกรอบ เข้า `main` แล้ว push (GitHub Pages เผยแพร่เองเพราะไฟล์ใน `site/` เปลี่ยน)
   ไม่ผ่าน หรือต้องแก้โค้ด/หน้าตา → push เข้ากิ่ง `agent/<วันที่>-<หัวข้อ>` และเปิด issue (ป้าย `editor-agent`) ไม่แตะ `main`
7. เขียนบันทึกรอบลงความจำ แล้วสรุปผลเป็นภาษาไทย

ขอบเขตที่ห้ามเกิน (เขียนไว้ใน system prompt และ `check.py --scope` ตรวจซ้ำ): บน `main` แก้ได้เฉพาะ `data/world-data.json`, `data/gold.json`,
`site/index.html` ที่สร้างใหม่ และไฟล์ใน `editor-agent/runs/` ห้ามแก้ workflow, secret, โค้ด updater, ชุดทดสอบ ห้าม force-push ห้ามลบประวัติ

## ไฟล์ในโฟลเดอร์นี้

| ไฟล์ | หน้าที่ |
|---|---|
| `agent/agent.json`, `agent/system_prompt.md` | นิยาม agent: โมเดล `claude-sonnet-5-5`, ชุดเครื่องมือ (bash, ไฟล์, web_search, web_fetch), คำสั่งงาน |
| `environment.json` | กล่องทำงานบนคลาวด์ (Ubuntu มี Python, Node, Playwright + Chromium ติดมาแล้ว) และแพ็กเกจ pip ที่ลงเพิ่ม |
| `memory_store.json`, `memory_seed/` | ความจำข้ามรอบ และไฟล์ตั้งต้นที่ใส่ไว้ตอนสร้าง |
| `deployment.json`, `kickoff/` | ตารางเวลา 07:00 กรุงเทพฯ, เพดาน 3 ดอลลาร์ต่อรอบ, ข้อความเริ่มงาน และเกณฑ์ตรวจผลงาน (rubric) |
| `lock.json` | รหัสของ agent / environment / memory store / deployment ที่สร้างแล้ว (ไม่มีความลับ ควร commit) |
| `setup.py` | สร้างหรืออัปเดตวัตถุทั้งหมดจากไฟล์ข้างบน แล้วจดรหัสลง `lock.json` ไม่ลบหรือ archive อะไรเลย |
| `run_once.py` | สั่งรันทดลอง 1 รอบและดูความคืบหน้า, ดูรายการรอบที่ผ่านมา, ตอบคำขออนุญาตที่ค้าง |
| `check.py`, `schema/` | ตรวจรูปแบบข้อมูลด้วย JSON Schema, วันที่ไม่ล้าหลัง, ชื่อเรื่องไม่มีเดือน, ทุกจุดที่เปลี่ยนมีแหล่งที่มา, ขอบเขตไฟล์, สุขภาพข้อมูลสด |
| `visual_check.py` | เปิดหน้าเว็บจริงแบบไม่มีหน้าต่าง หา error, แผงว่าง, วันที่ไม่ตรง, ล้นจอ (ค่าที่คาดหวังอ่านจากข้อมูล ไม่ฝังตายตัว) |
| `e2e.sh` | รันชุดทดสอบ `e2e/` ในกล่องของ agent โดยใช้ Chromium ที่ติดมากับกล่อง |
| `tests/` | ทดสอบ `check.py` และนิยามต่าง ๆ (ไม่ใช้เน็ต): `.venv/bin/python -m pytest editor-agent/tests -q` |
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
   สคริปต์ถามยืนยัน พิมพ์ลิงก์ Console แสดงทุกขั้น (ค้นอะไร เปิดหน้าไหน รันคำสั่งอะไร) ผลตรวจของผู้ตรวจ (grader) และค่าใช้จ่ายสุดท้าย
4. **เปิดตารางเวลา** เมื่อรอบทดลองผ่าน:
   ```bash
   ANTHROPIC_API_KEY="$(cat $K)" .venv/bin/python editor-agent/setup.py --apply --deployment
   ```
   จะเริ่มรันทุกวัน 07:00 น. (อาจช้าได้ถึง 9 นาที) ทดลองสั่งรอบของ deployment ทันที: `run_once.py deployment-run`

เปลี่ยน prompt / rubric / ตารางเวลา: แก้ไฟล์แล้วรัน `setup.py --apply` (เพิ่ม `--deployment` ถ้าแก้ `deployment.json` หรือ `kickoff/`)
agent จะได้เวอร์ชันใหม่ รอบถัดไปใช้เวอร์ชันล่าสุดเอง เปลี่ยน token แล้ว: `setup.py --apply --deployment --refresh-token`

## ค่าใช้จ่าย

แต่ละรอบเป็น 1 session คิดเงิน 3 ส่วน:

- **โทเค็น** Claude Sonnet 5.5: อินพุต 2 ดอลลาร์ต่อล้าน, เอาต์พุต 10, เขียนแคช 2.50, อ่านแคช 0.10 (ประวัติการทำงานถูกแคชให้อัตโนมัติ)
- **ค้นเว็บ** 10 ดอลลาร์ต่อ 1,000 ครั้ง (40 ครั้ง = 0.40 ดอลลาร์) เปิดหน้าเว็บด้วย web_fetch ไม่คิดต่อครั้ง จ่ายเฉพาะโทเค็นของเนื้อหา (จำกัดหน้าละ 8,000 โทเค็น)
- **เวลาที่ session ทำงาน** 0.08 ดอลลาร์ต่อชั่วโมง (รอบละราว 30–60 นาที ≈ 0.04–0.08)

ประมาณการก่อนรันจริง: รอบละ 1.5–2.5 ดอลลาร์ (ค้นเว็บ ~0.4, อ่านแคช ~0.5, อินพุตใหม่และเขียนแคช ~0.8, เอาต์พุต ~0.5, ผู้ตรวจ rubric ~0.2)
เพดานแข็งรอบละ **3.00 ดอลลาร์** (ถึงเพดานแล้วหยุดรอ ไม่ทำงานต่อ) จึงไม่เกินราว 93 ดอลลาร์ต่อเดือน รวมกับบอตเดิม (~60 ดอลลาร์ต่อเดือน)
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

- Console: <https://platform.claude.com> → Managed Agents → **Sessions** (บันทึกทุกขั้น ค่าใช้จ่าย ผลของ grader) และ **Deployments** (ตารางเวลา รอบที่รันแล้ว)
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

- ชุดทดสอบ `e2e/` ยังฝังค่าข้อมูลตายตัว (จำนวน 25 ความขัดแย้ง, '$3,903', 'ณ 2 พ.ย.' ฯลฯ) พอข้อมูลเปลี่ยนจะล้ม agent จึงถือว่าความล้มเหลวแบบนี้ "คาดไว้แล้ว" และใช้ `visual_check.py` เป็นด่านหลักแทน จนกว่า e2e จะอ่านค่าจากข้อมูล
- ยังไม่ได้ยืนยันในรอบจริงว่าเปิด issue ผ่าน REST API ด้วย git proxy ได้ ถ้าไม่ได้ agent จะเขียน issue เป็นไฟล์ในกิ่ง `agent/<วันที่>-issues` และจดไว้ในความจำ
- ยังไม่ได้ยืนยันว่า `e2e.sh` ใช้ Chromium ในกล่องกับ `@playwright/test` 1.56.1 ได้ (ถ้าไม่ได้ จะออกรหัส 3 และไม่ขวางการ push)
