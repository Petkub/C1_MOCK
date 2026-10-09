ข้อสอบจำลองภาคปฏิบัติ สอวน. คอมพิวเตอร์ ค่าย 1 — 15 ชุด ชุดละ 8 ข้อ (3 ชั่วโมง)
==========================================================================

โครงสร้างโฟลเดอร์
  Guide.pdf        คู่มือ: วิเคราะห์ข้อสอบ วิธีคิด 4 ขั้น ภาพรวม 15 ชุด และวิธีฝึก (อ่านก่อน)
  Mock_1 ... Mock_15
      Mock_K.pdf   โจทย์ชุดที่ K (หน้าปก + 8 ข้อ)
      1.cpp ... 8.cpp   ไฟล์คำตอบของแต่ละข้อ (เขียน code ลงไฟล์เหล่านี้ได้เลย)
  Judge            ตัวตรวจและชุดทดสอบ (ไม่ต้องแก้อะไรในโฟลเดอร์นี้)

วิธีตรวจ (ต้องมี Python 3.7+ และ g++) — เลือกวิธีที่สะดวก
  ก) VS Code (ง่ายที่สุด): File > Open Folder... เลือกโฟลเดอร์ Mock_Test (ไม่ใช่ Mock_3)
     เปิดไฟล์ที่ทำ เช่น Mock_3/5.cpp แล้วกด Ctrl+Shift+B (Mac: Cmd+Shift+B) = ตรวจข้อนั้น
     ตรวจทั้งชุด: Terminal > Run Task... > Judge whole set
  ข) terminal ในโฟลเดอร์ชุดที่ทำ (เช่น cd Mock_3)
       Linux / macOS     make          (ทั้งชุด)     make 5          (เฉพาะข้อ 5)
       Windows           judge         (ทั้งชุด)     judge 5         (PowerShell: .\judge 5)
     หรือดับเบิลคลิก judge.bat ในโฟลเดอร์ชุดนั้น (Windows) เพื่อตรวจทั้งชุด
     (ถ้าไม่มีคำสั่ง make: Linux ใช้ sudo apt install make · macOS มากับ xcode-select --install)
  ค) เรียก judge ตรง ๆ (ทุกระบบ):  python3 ../Judge/judge.py   หรือ   python3 ../Judge/judge.py 5.cpp
     Windows ใช้ python แทน python3

macOS (ทำครั้งเดียว)
  - ติดตั้ง compiler + Python:  xcode-select --install
  - g++ บน Mac คือ clang ซึ่งไม่มี <bits/stdc++.h>  judge จัดการให้เองแล้ว (ใช้ Judge/include)
    แต่ถ้าจะ compile เองด้วย g++ หรือใน VS Code ให้ติดตั้ง header นี้ครั้งเดียว (ในโฟลเดอร์ Mock_Test):
      sudo mkdir -p /usr/local/include/bits
      sudo cp Judge/include/bits/stdc++.h /usr/local/include/bits/

ตัวเลือกเพิ่มเติม: --tl 2 (เวลาต่อชุดทดสอบ) --stop (หยุดที่ชุดแรกที่ผิด) --ascii --no-color
ดูรายชื่อโจทย์ทั้งหมด: python3 ../Judge/judge.py --list
ถ้าคัดลอกโฟลเดอร์ ให้ตั้งชื่อเป็น Mock_K เสมอ (judge ดูเลขชุดจากชื่อโฟลเดอร์) หรือระบุเอง: python3 ../Judge/judge.py 5.cpp 3-5

คะแนน: ข้อละ 100 คิดตามสัดส่วนชุดทดสอบที่ผ่าน (ข้อที่มีปัญหาย่อย คิดแยกแต่ละปัญหาย่อย)
ชุดทดสอบ 5–6 ชุดแรกของแต่ละข้อคือตัวอย่างในโจทย์
