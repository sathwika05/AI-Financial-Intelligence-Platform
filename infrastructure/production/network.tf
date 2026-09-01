// `locals` are computed values, evaluated once and referenced as local.<name>.
// Unlike variables they can reference other values, so they are the right
// place for anything derived.
locals {
  name_prefix = "${var.project}-${var.environment}"

  // Two AZs because RDS subnet groups require at least two, even for a
  // single-AZ instance. `slice` takes the first two the account can use,
  // so this works in any region without hardcoding zone names.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  // cidrsubnet(prefix, newbits, netnum) carves a subnet out of the VPC
  // range. From 10.0.0.0/16 with 8 new bits: 10.0.0.0/24, 10.0.1.0/24, ...
  // Computing these avoids a wall of hand-written CIDRs that drift.
  public_subnet_cidrs  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnet_cidrs = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i + 10)]
}

resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  // Both required for RDS to get a resolvable hostname.
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

// ---------------------------------------------------------------------------
// Subnets
//
// `count` creates N copies of a resource. Inside the block, count.index is
// the current position, and the whole set is referenced as a list:
// aws_subnet.public[0], or aws_subnet.public[*].id for all of them.
//
// count is right here because the subnets are identical apart from their
// index. Prefer for_each when items have distinct identities — count
// addresses by position, so removing the first element renumbers every
// subsequent one and Terraform destroys and recreates them all.
// ---------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = length(local.azs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.public_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${count.index + 1}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count = length(local.azs)

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${count.index + 1}"
    Tier = "private"
  }
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

// A conditional resource: `count` of 0 creates nothing, 1 creates one. This
// is how Terraform expresses "only if", since there is no if statement.
//
// Guarded because a NAT Gateway is billed hourly plus per GB whether or not
// it is used, and is usually the largest cost in a stack like this.
resource "aws_eip" "nat" {
  count = var.use_nat_gateway ? 1 : 0

  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-eip"
  }
}

resource "aws_nat_gateway" "main" {
  count = var.use_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  // Terraform infers ordering from references, but nothing here references
  // the gateway, and NAT creation fails without it. This is the case
  // depends_on exists for.
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.name_prefix}-nat"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  // `dynamic` generates zero or more nested blocks. With no NAT gateway the
  // private route table simply has no default route, leaving those subnets
  // isolated rather than broken.
  dynamic "route" {
    for_each = var.use_nat_gateway ? [1] : []

    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.main[0].id
    }
  }

  tags = {
    Name = "${local.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count = length(aws_subnet.private)

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

// ---------------------------------------------------------------------------
// Security groups
//
// These reference each other rather than naming CIDRs: the database accepts
// connections from the application's security group, not from an IP range.
// Membership then follows the resource wherever it runs.
// ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-sg"
  description = "Public entry point"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere, redirected to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-alb-sg"
  }
}

resource "aws_security_group" "app" {
  name        = "${local.name_prefix}-app-sg"
  description = "Fargate tasks: API and indexing worker"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "From the load balancer only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  // Outbound is open because tasks call OpenAI, Groq, Alpha Vantage and
  // Yahoo. Without a NAT gateway this egress runs through the task's own
  // public IP.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-app-sg"
  }
}

resource "aws_security_group" "db" {
  name        = "${local.name_prefix}-db-sg"
  description = "Postgres, reachable only from application tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from app tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  tags = {
    Name = "${local.name_prefix}-db-sg"
  }
}
