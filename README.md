CivicConnect - Civic Grievance Management Platform
CivicConnect is a full-stack web application that bridges the gap between citizens and local government departments. Citizens can report civic issues like broken roads, water problems, or damaged public property, track complaint status in real-time, and download official PDF reports. Government departments manage assigned complaints through their own portal, while an admin panel provides complete oversight with analytics and department management.

Technology Stack

Backend: Python, Flask, Flask-CORS, PyMongo, Werkzeug
Database: MongoDB (flexible document structure for complaint records)
Frontend: HTML5, CSS3, JavaScript, Jinja2 templates
Maps: Leaflet.js (interactive complaint location pinning)
AI: Ollama local LLM (title suggestion and description enhancement)
Document Export: ReportLab (PDF), OpenPyXL (Excel)
Auth: Email OTP verification, session-based multi-role login


Features and Functionalities
Citizen Portal:

Register with email OTP verification for secure, verified accounts
Submit complaints via a 3-step form — Details, Photos, and Location
AI Suggest and AI Enhance buttons to improve complaint title and description
Pin exact issue location on an interactive map or use GPS auto-detect
Track complaint progress through Submitted, In Progress, and Resolved stages
View department updates and download any complaint as a PDF

Department Portal:

Dedicated login for each department (Public Works, Water, Roads, Electricity, etc.)
View and manage only the complaints assigned to that department
Update complaint status and add resolution remarks visible to the citizen

Admin Panel:

View and manage all complaints across all departments
Create departments and monitor their credentials and complaint load
Analytics dashboard with category breakdown charts, SLA performance, resolution rates, and average resolution speed
Export complaint data as Excel reports


Installation and Setup
Prerequisites: Python 3.10+, MongoDB running locally, Git
Step 1 - Clone the repository:
git clone https://github.com/your-username/CivicConnect.git
cd CivicConnect
Step 2 - Install dependencies:
pip install -r requirements.txt
Step 3 - Configure environment:
create your own .env file
Step 4 - Run the application:
python app.py
Step 5 - Open in browser:
http://localhost:5000
Default admin login — Email: admin@civic.gov (password set on first run)
Department logins are visible in the Admin panel under Departments.

Team Members:

Mayank Pawar — Medicaps University, B.Tech Computer Science and Engineering


Project Screenshots

Home Page — Landing page with Submit a Complaint and Track My Complaint buttons, live complaint activity feed, category shortcuts, and platform-wide stats.
Login Page — Role-based login with tabs for Citizen and Admin/Department access.
Register Page — 3-step citizen registration with email OTP verification (Details, Verify Email, Done).
Citizen Dashboard — Summary cards for total, pending, in-progress, and resolved complaints with a recent complaints table and quick action shortcuts.
Submit Complaint — Split-screen form with multi-step complaint entry on the left and an interactive satellite map for location pinning on the right.
My Complaints and Detail View — Complaint list table with a modal showing full complaint details, progress tracker, photos, location, and department updates.
Admin Departments — Department cards showing complaint stats, resolution rates, and login credentials for all 7 departments.
Admin Analytics — Category breakdown bar chart, department SLA performance bars, resolution speed table, and full department performance report.
