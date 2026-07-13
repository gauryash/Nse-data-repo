This is actually one of my favorite stacks for small projects. It is **100% GitHub + Cloudflare**, costs **₹0**, and scales surprisingly well. No VPS, no Docker, no waking up to "your free instance has gone to sleep." Civilization advances one tiny step. 😄

# Final Architecture

```text
GitHub Repository
│
├── frontend/      (HTML/CSS/JS)
│
└── worker/        (Cloudflare Worker API)

        │
        ▼
Cloudflare Worker
        │
        ▼
Cloudflare D1 Database
```

* **GitHub** stores all your code.
* **GitHub Pages** hosts the frontend.
* **Cloudflare Worker** is your backend.
* **Cloudflare D1** is your SQL database. ([Cloudflare Docs][1])

---

# Step 1. Create a GitHub Repository

Create a repository like:

```text
my-app
```

Structure it like this:

```text
my-app
│
├── frontend
│   ├── index.html
│   ├── style.css
│   └── app.js
│
└── worker
```

Commit it.

---

# Step 2. Enable GitHub Pages

Go to

```
GitHub
→ Repository
→ Settings
→ Pages
```

Choose

```
Deploy from branch
```

Select

```
main
```

Folder

```
/frontend
```

Save.

After a minute you'll get

```text
https://yourname.github.io/my-app
```

Your frontend is live.

---

# Step 3. Create a Cloudflare Account

Go to:

[Cloudflare Dashboard](https://dash.cloudflare.com?utm_source=chatgpt.com)

Sign in.

---

# Step 4. Install Node.js

Download:

[Node.js](https://nodejs.org?utm_source=chatgpt.com)

Verify

```bash
node -v
npm -v
```

---

# Step 5. Install Wrangler

Wrangler is Cloudflare's CLI.

```bash
npm install -g wrangler
```

Check

```bash
wrangler --version
```

---

# Step 6. Login

```bash
wrangler login
```

Browser opens.

Authorize Cloudflare.

Done.

---

# Step 7. Create the Worker

Inside your project

```bash
cd worker
```

Run

```bash
npm create cloudflare@latest .
```

Choose

```
Hello World
```

Then

```
Worker only
```

Then

```
TypeScript
```

When asked

```
Deploy now?
```

Choose

```
No
```

Cloudflare recommends this workflow for new Worker projects. ([Cloudflare Docs][1])

Your folder becomes

```text
worker
│
├── src
│     index.ts
│
├── package.json
│
└── wrangler.jsonc
```

---

# Step 8. Create a Database

Run

```bash
wrangler d1 create mydb
```

Output looks like

```text
database_id = xxxxx-xxxx-xxxx
binding = DB
```

Wrangler can automatically add the binding to your configuration. ([Cloudflare Docs][1])

---

# Step 9. Create the First Table

Create

```text
schema.sql
```

Inside

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER
);
```

Run

```bash
wrangler d1 execute mydb --file=schema.sql --remote
```

Database ready.

---

# Step 10. Write Your Backend

Replace

```text
src/index.ts
```

with

```ts
export interface Env {
  DB: D1Database;
}

export default {
  async fetch(request: Request, env: Env) {

    await env.DB.prepare(
      "INSERT INTO users(name,age) VALUES (?,?)"
    )
    .bind("Yash", 22)
    .run();

    const data = await env.DB
      .prepare("SELECT * FROM users")
      .all();

    return Response.json(data.results);
  }
}
```

This inserts a row and returns every user.

---

# Step 11. Deploy

```bash
wrangler deploy
```

You'll receive

```text
https://your-worker.workers.dev
```

Backend finished.

---

# Step 12. Connect Frontend

Inside

```javascript
app.js
```

```javascript
fetch("https://your-worker.workers.dev")
  .then(r => r.json())
  .then(data => {
      console.log(data);
  });
```

Your GitHub Pages website is now talking to your Cloudflare backend.

---

# Step 13. Push Everything to GitHub

```bash
git add .
git commit -m "Initial project"
git push
```

GitHub stores:

* frontend
* worker source code

Cloudflare stores:

* deployed Worker
* database

---

# Step 14. Update Later

Whenever you change the backend:

```bash
wrangler deploy
```

Whenever you change the frontend:

```bash
git push
```

GitHub Pages updates automatically.

---

# Project Structure

```text
my-app/
│
├── frontend/
│     index.html
│     app.js
│     style.css
│
└── worker/
      src/
      package.json
      wrangler.jsonc
```

---

## What you'll end up with

| Component   | Service                                     |
| ----------- | ------------------------------------------- |
| Frontend    | GitHub Pages                                |
| Backend API | Cloudflare Workers                          |
| Database    | Cloudflare D1                               |
| Source Code | GitHub                                      |
| Cost        | **Free** (within generous free-tier limits) |

This is a clean, production-style architecture that's great for personal projects, portfolios, dashboards, and lightweight web apps. 🚀

The only thing I'd do differently from many tutorials is make deployment even smoother by using **GitHub Actions** so that every `git push` automatically deploys both your GitHub Pages frontend and your Cloudflare Worker. That way, GitHub becomes the single place you work from, and Cloudflare simply updates itself whenever your code changes.

[1]: https://developers.cloudflare.com/d1/get-started/?utm_source=chatgpt.com "Getting started · Cloudflare D1 docs"
