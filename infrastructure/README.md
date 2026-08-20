# Infrastructure

Two deployments with deliberately different shapes.

| | `production/` | `preprod/` |
|---|---|---|
| Platform | AWS, via Terraform | Render (API) + Vercel (UI) |
| Lifecycle | Created and destroyed on demand | Always on |
| Auth | Login, admin + user roles | **None** — public demo |
| Admin routes | Mounted | **Not mounted** |
| LLM | OpenAI / Anthropic / Gemini | Groq |
| Embeddings | OpenAI | OpenAI (the only paid call) |
| Database | RDS + pgvector | Neon + pgvector |
| Queue / storage | SQS + S3 | none |
| Cost | Hours used × rate | ~free |

The names follow the deployment's purpose, not its uptime: `production` is
the complete system including the indexing pipeline and benchmarking;
`preprod` is the public showcase.

## production/ — AWS

```
providers.tf   provider config, version pins, state backend
variables.tf   inputs; db_password has no default on purpose
network.tf     VPC, subnets, routing, security groups
storage.tf     S3 buckets, SQS queue + DLQ, S3 -> SQS notification
database.tf    RDS Postgres 16, parameter group, subnet group
compute.tf     ECS cluster, task definitions, services, ALB, IAM, logs
outputs.tf     values the application and you need after apply
```

```bash
cd infrastructure/production
cp terraform.tfvars.example terraform.tfvars   # set db_password
terraform init
terraform plan      # read this before applying
terraform apply
terraform destroy   # removes everything Terraform created
```

### Two things that decide the bill

**`use_nat_gateway` defaults to `false`.** A NAT Gateway costs roughly
$32/month whether traffic flows or not, which on a stack meant to be
destroyed between sessions is usually the largest line. With it off,
Fargate tasks sit in public subnets with public IPs, reachable only through
their security group. Set it `true` for anything long-lived.

**Terraform must own everything.** Resources created by hand in the console
are invisible to Terraform, so `destroy` leaves them running and billing.
Use the console to look, not to create.

### What Terraform does not do

- Build or push the container image; set `container_image` to an existing tag
- Run `alembic upgrade head`
- Seed data
- Create the `vector` extension — `backend/main.py` does that at startup

## preprod/ — Render + Vercel

```
render.yaml    API service, env vars, health check
vercel.json    frontend build and /api proxy to Render
```

The API cannot be a Vercel function: a query takes around 95 seconds, well
past serverless timeouts. Vercel serves the built frontend and proxies
`/api/*` to Render.

### Standing it up

1. Neon project, then `CREATE EXTENSION IF NOT EXISTS vector;`
2. `SYNC_DATABASE_URL=<neon> uv run alembic upgrade head`
3. `DATABASE_URL=<neon> uv run python -m seeds.snapshot restore` — the
   frozen snapshot rather than a reseed, so no API quota is spent and the
   demo matches what has been benchmarked
4. Set the secret env vars in the Render dashboard
5. Deploy the frontend to Vercel, pointing the rewrite at the Render URL

### Why this is safe to expose

Three things, and all three are needed:

- `DEPLOYMENT_MODE=portfolio` leaves the evaluation and indexing routers
  unmounted, so admin endpoints do not exist rather than being hidden
- Groq serves the chat models, so an unauthenticated endpoint cannot run up
  a bill
- `RATE_LIMIT_PER_HOUR` caps requests per IP, which matters because Groq's
  free tier limits requests per minute and a loop would exhaust it

OpenAI is still called once per query for the search embedding — about
$0.00000002. Put a hard spend limit on the key anyway.
