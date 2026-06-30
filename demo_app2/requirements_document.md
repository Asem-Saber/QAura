# E-Learning Platform — Requirements for Testing

## Application Overview
A Django-based e-learning platform that allows students to browse and apply for courses, and enables administrators to manage courses and students. It features a simple authentication system (signup/login) and uses JWT for API access authorization.

## Source Files Under Test
- `e-learning-platform-using-django/courses/models.py` — Database schema (SystemAdmin, Course, Student, CourseRequest)
- `e-learning-platform-using-django/courses/urls.py` — Application routing and API endpoints
- `e-learning-platform-using-django/courses/views.py` — Business logic, page rendering, and RESTful API functions
- `e-learning-platform-using-django/e_learning/urls.py` — Main project routing
- `e-learning-platform-using-django/templates/` — HTML frontend pages

## Functional Requirements
1. Students can register for a new account with a username and password.
2. Students can log in to receive an authentication token (JWT).
3. Authenticated and unauthenticated users can browse all available courses.
4. Students can view detailed descriptions of individual courses.
5. Authenticated students can submit a request to enroll in a specific course.
6. A student can only request enrollment for a specific course once.
7. Students can view their profile and a list of their enrolled courses.
8. System administrators can manage (add, edit, delete) courses and students via the Django admin panel.

## Known Risk Areas (for QAura to discover)
- JWT token expiration, validation, and storage mechanisms.
- Authentication and authorization bypass on API endpoints (e.g., accessing `/student_info/` without a valid token).
- Cross-Site Scripting (XSS) in the course request reason field or profile details.
- Insecure Direct Object Reference (IDOR) vulnerabilities (e.g., a student trying to view another student's info or enrolled courses).
- SQL Injection in custom database queries or poorly handled ORM filters.
- File upload vulnerabilities (e.g., uploading malicious files for course images in `Course` model).
- Weak password hashing or storage practices for `Student` and `SystemAdmin` models.
- Missing CSRF protection on forms and API state-changing requests.

## API Endpoints
- **POST** `/signup/` — Register a new student
- **POST** `/login/` — Login and receive a JWT token
- **GET** `/all_courses/` — Retrieve a list of all courses
- **GET** `/get_course/` — Retrieve details for a specific course
- **POST** `/creat_course_request/` — Submit a request for a course (requires auth)
- **GET** `/get_course_request/` — Retrieve a student's course requests (requires auth)
- **GET** `/student_info/` — Retrieve the currently logged-in student's information (requires auth)

## Frontend Pages
- `/` (Home/Index) — Main landing page displaying available courses
- `/login_page/` — Student login form
- `/signup_page/` — Student registration form
- `/course_description_page/` — Detailed view of a selected course
- `/profile_page/` — User profile details
- `/request_page/` — Form/page to submit a course request
- `/enrolled_courses_page/` — Dashboard showing a student's enrolled courses
