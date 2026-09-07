# Email Builder AI Agent prompts

The Email Builder agents live in the `AI Agent` doctype, which means their
prompts, output schemas, temperature and token limits are **database rows** and
were previously invisible to code review, diffable only by hand, and impossible
to roll back. This directory makes them source.

```
agents/
  agents.json            agent config: model, temperature, max_tokens, file wiring
  prompts/*.md           prompt message bodies, written in natural syntax
  schemas/*.json         structured-output JSON schemas
  backup/                point-in-time captures of the live DB state
  sync.py                push files -> DB, pull DB -> files
```

## Why prompts are not written with LangChain escaping

`AgentService` renders every prompt through `ChatPromptTemplate`, which uses
f-string syntax: `{name}` is substituted, and a literal brace must be doubled.

That detail cost us every merge field in every generated email. The prompt
said

    PRESERVE MERGE TOKENS: ... like {{ doc.first_name }}

intending to show the model a `{{ ... }}` token. `ChatPromptTemplate` collapsed
`{{` to `{`, so what the model actually received was `{ doc.first_name }` — and
it copied that faithfully into every template it generated. `TOKEN_RE` only
matches `{{ ... }}`, so those tokens were never compiled; they shipped as
literal text, and every button href read `https://{ doc.dashboard_link }`.

So the files here are written in **plain, natural syntax**. Braces mean braces.
`sync.py` escapes the entire body mechanically, then substitutes variables
written as `<<variable_name>>`:

    Current design: <<current_schema>>     ->  Current design: {current_schema}
    Use {{ first_name }} for merge fields  ->  Use {{{{ first_name }}}} ...

You cannot get the escaping wrong, because you never write it.

## Usage

    # Preview what would change, without writing
    bench --site <site> execute finbyzreach.email_template_builder.agents.sync.push --kwargs "{'dry_run': True}"

    # Apply the files to the database
    bench --site <site> execute finbyzreach.email_template_builder.agents.sync.push

    # Capture the live database state back into backup/
    bench --site <site> execute finbyzreach.email_template_builder.agents.sync.pull

`push` always writes a fresh `backup/` capture before it changes anything, so
the previous state is recoverable via `restore`.

    bench --site <site> execute finbyzreach.email_template_builder.agents.sync.restore --kwargs "{'path': 'backup/ai-agents-....json'}"

## The two agents are deliberately different

`Email Builder Generator` writes a template from a blank page: it needs the
full design system and no instruction to preserve anything. `Email Builder
Copilot` edits an existing design: it needs the opposite — a strong bias
toward leaving untouched everything the user did not ask about. They shared a
byte-identical prompt until this change, which is why the generator kept being
told to "PRESERVE EXISTING CONTENT" of a template that did not exist yet.
