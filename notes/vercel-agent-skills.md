# vercel-labs/agent-skills

Source: https://github.com/vercel-labs/agent-skills (checked at commit `063bee9`, 2026-08-28)

## Install on your PC (needs Node.js)

```bash
# Pick skills interactively
npx skills add vercel-labs/agent-skills

# Everything, user-level (all projects), for Claude Code, no prompts
npx skills add vercel-labs/agent-skills --skill '*' -a claude-code -g -y

# Only some skills
npx skills add vercel-labs/agent-skills -s web-design-guidelines -s vercel-react-best-practices -g

# See what's in the repo without installing
npx skills add vercel-labs/agent-skills --list
```

`-g` installs globally (every project on the PC). Leave it out to install into the current project only.
Manage later with `npx skills list`, `npx skills update`, `npx skills remove`.

## The 9 skills

| Skill name (for `-s`) | What it does |
|---|---|
| `vercel-react-best-practices` | React / Next.js performance rules from Vercel Engineering: data fetching, bundle size, rendering. |
| `vercel-composition-patterns` | React component architecture: compound components, render props, context, avoiding boolean-prop sprawl. Includes React 19 changes. |
| `vercel-react-view-transitions` | Page/route transitions and shared-element animations with React's View Transition API. |
| `vercel-react-native-skills` | React Native + Expo best practices: list performance, animations, native modules. |
| `web-design-guidelines` | Reviews UI code against Vercel's Web Interface Guidelines ("review my UI", "check accessibility"). |
| `writing-guidelines` | Reviews docs/prose for voice, tone and style. |
| `deploy-to-vercel` | Deploys an app to Vercel and returns the link (preview or production). |
| `vercel-cli-with-tokens` | Vercel CLI with access tokens instead of interactive login: deploys, env vars, project setup. |
| `vercel-optimize` | Cost and performance review of a deployed Vercel project (Next.js, SvelteKit, Nuxt, Astro), with ranked recommendations from real metrics. |

Most useful for this repo (UI/UX work): `web-design-guidelines`, `vercel-react-best-practices`,
`vercel-composition-patterns`, `vercel-react-view-transitions`.

## Other tools mentioned in the same chat

- **Graphify** (code -> knowledge graph): `uv tool install graphifyy` then `graphify install`; use `/graphify .`
- **Caveman** (terse replies): Claude account -> Customize > Plugins -> Add marketplace `JuliusBrussee/caveman`;
  or CLI: `claude plugin marketplace add JuliusBrussee/caveman && claude plugin install caveman@caveman`
- **Superpowers**: `/plugin install superpowers@claude-plugins-official`
- **Magic UI MCP**: `pnpm dlx @magicuidesign/cli@latest install claude` (this repo's `.mcp.json` already has it)
