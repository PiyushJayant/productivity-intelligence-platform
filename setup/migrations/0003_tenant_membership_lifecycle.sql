-- Authoritative, revocable tenant membership and administration contracts.
ALTER TABLE tenant_memberships
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE tenant_memberships
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE tenant_memberships
  ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tenant_membership_status_valid'
  ) THEN
    ALTER TABLE tenant_memberships
      ADD CONSTRAINT tenant_membership_status_valid
      CHECK (status IN ('active', 'revoked'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS tenant_memberships_active_subject_idx
  ON tenant_memberships(subject_id, tenant_id)
  WHERE status = 'active';

CREATE OR REPLACE FUNCTION enforce_active_membership()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM tenant_memberships AS m
    JOIN tenants AS t ON t.id = m.tenant_id
    JOIN subjects AS s ON s.id = m.subject_id
    WHERE m.tenant_id = NEW.tenant_id
      AND m.subject_id = NEW.created_by_subject_id
      AND m.status = 'active'
      AND t.status = 'active'
      AND s.disabled_at IS NULL
      AND m.role IN ('owner', 'admin', 'member')
  ) THEN
    RAISE EXCEPTION 'active tenant membership is required'
      USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION tenant_actor_role(
  p_tenant_id UUID,
  p_actor_subject_id UUID
)
RETURNS TEXT
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT m.role
  FROM tenant_memberships AS m
  JOIN tenants AS t ON t.id = m.tenant_id
  JOIN subjects AS s ON s.id = m.subject_id
  WHERE m.tenant_id = p_tenant_id
    AND m.subject_id = p_actor_subject_id
    AND m.status = 'active'
    AND t.status = 'active'
    AND s.disabled_at IS NULL
$$;

CREATE OR REPLACE FUNCTION authorize_identity(
  p_tenant_id UUID,
  p_subject_id UUID,
  p_issuer TEXT,
  p_external_subject TEXT
)
RETURNS TABLE(role TEXT)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT m.role
  FROM tenant_memberships AS m
  JOIN tenants AS t ON t.id = m.tenant_id
  JOIN subjects AS s ON s.id = m.subject_id
  WHERE m.tenant_id = p_tenant_id
    AND m.subject_id = p_subject_id
    AND m.status = 'active'
    AND t.status = 'active'
    AND s.disabled_at IS NULL
    AND s.issuer = p_issuer
    AND s.external_subject = p_external_subject
$$;

CREATE OR REPLACE FUNCTION list_tenant_members(
  p_tenant_id UUID,
  p_actor_subject_id UUID
)
RETURNS TABLE(
  subject_id UUID,
  external_subject TEXT,
  role TEXT,
  status TEXT,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF tenant_actor_role(p_tenant_id, p_actor_subject_id)
      NOT IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'tenant administration is not authorized'
      USING ERRCODE = '42501';
  END IF;
  RETURN QUERY
    SELECT m.subject_id, s.external_subject, m.role, m.status,
      m.created_at, m.updated_at
    FROM tenant_memberships AS m
    JOIN subjects AS s ON s.id = m.subject_id
    WHERE m.tenant_id = p_tenant_id
    ORDER BY m.created_at, m.subject_id;
END
$$;

CREATE OR REPLACE FUNCTION provision_tenant_member(
  p_tenant_id UUID,
  p_actor_subject_id UUID,
  p_target_subject_id UUID,
  p_issuer TEXT,
  p_external_subject TEXT,
  p_role TEXT
)
RETURNS TABLE(subject_id UUID, external_subject TEXT, role TEXT, status TEXT)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE actor_role TEXT;
BEGIN
  actor_role := tenant_actor_role(p_tenant_id, p_actor_subject_id);
  IF actor_role NOT IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'tenant administration is not authorized'
      USING ERRCODE = '42501';
  END IF;
  IF p_role NOT IN ('owner', 'admin', 'member', 'viewer') THEN
    RAISE EXCEPTION 'unsupported tenant role' USING ERRCODE = '22023';
  END IF;
  IF actor_role = 'admin' AND p_role IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'only an owner can provision privileged roles'
      USING ERRCODE = '42501';
  END IF;
  IF btrim(p_issuer) = '' OR btrim(p_external_subject) = '' THEN
    RAISE EXCEPTION 'external identity is required' USING ERRCODE = '22023';
  END IF;

  INSERT INTO subjects(id, issuer, external_subject)
  VALUES (p_target_subject_id, p_issuer, p_external_subject)
  ON CONFLICT (id) DO UPDATE
    SET disabled_at = NULL
    WHERE subjects.issuer = EXCLUDED.issuer
      AND subjects.external_subject = EXCLUDED.external_subject;
  IF NOT EXISTS (
    SELECT 1 FROM subjects AS target_subject
    WHERE target_subject.id = p_target_subject_id
      AND target_subject.issuer = p_issuer
      AND target_subject.external_subject = p_external_subject
  ) THEN
    RAISE EXCEPTION 'subject identity does not match its deterministic ID'
      USING ERRCODE = '23514';
  END IF;

  INSERT INTO tenant_memberships(tenant_id, subject_id, role, status)
  VALUES (p_tenant_id, p_target_subject_id, p_role, 'active')
  ON CONFLICT ON CONSTRAINT tenant_memberships_pkey DO UPDATE
    SET role = EXCLUDED.role, status = 'active', revoked_at = NULL,
      updated_at = now();

  RETURN QUERY SELECT p_target_subject_id, p_external_subject, p_role, 'active';
END
$$;

CREATE OR REPLACE FUNCTION update_tenant_member_role(
  p_tenant_id UUID,
  p_actor_subject_id UUID,
  p_target_subject_id UUID,
  p_role TEXT
)
RETURNS TABLE(subject_id UUID, role TEXT, status TEXT)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE actor_role TEXT;
DECLARE target_role TEXT;
BEGIN
  actor_role := tenant_actor_role(p_tenant_id, p_actor_subject_id);
  SELECT m.role INTO target_role FROM tenant_memberships AS m
  WHERE m.tenant_id = p_tenant_id AND m.subject_id = p_target_subject_id
    AND m.status = 'active' FOR UPDATE;
  IF actor_role NOT IN ('owner', 'admin') OR target_role IS NULL THEN
    RAISE EXCEPTION 'membership update is not authorized'
      USING ERRCODE = '42501';
  END IF;
  IF p_role NOT IN ('owner', 'admin', 'member', 'viewer') THEN
    RAISE EXCEPTION 'unsupported tenant role' USING ERRCODE = '22023';
  END IF;
  IF actor_role = 'admin' AND (
    target_role IN ('owner', 'admin') OR p_role IN ('owner', 'admin')
  ) THEN
    RAISE EXCEPTION 'only an owner can modify privileged roles'
      USING ERRCODE = '42501';
  END IF;
  IF target_role = 'owner' AND p_role <> 'owner' AND (
    SELECT count(*) FROM tenant_memberships AS owner_membership
    WHERE owner_membership.tenant_id = p_tenant_id
      AND owner_membership.role = 'owner'
      AND owner_membership.status = 'active'
  ) <= 1 THEN
    RAISE EXCEPTION 'the last tenant owner cannot be demoted'
      USING ERRCODE = '23514';
  END IF;
  UPDATE tenant_memberships AS m
  SET role = p_role, updated_at = now()
  WHERE m.tenant_id = p_tenant_id AND m.subject_id = p_target_subject_id;
  RETURN QUERY SELECT p_target_subject_id, p_role, 'active';
END
$$;

CREATE OR REPLACE FUNCTION revoke_tenant_member(
  p_tenant_id UUID,
  p_actor_subject_id UUID,
  p_target_subject_id UUID
)
RETURNS TABLE(subject_id UUID, role TEXT, status TEXT)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE actor_role TEXT;
DECLARE target_role TEXT;
BEGIN
  actor_role := tenant_actor_role(p_tenant_id, p_actor_subject_id);
  SELECT m.role INTO target_role FROM tenant_memberships AS m
  WHERE m.tenant_id = p_tenant_id AND m.subject_id = p_target_subject_id
    AND m.status = 'active' FOR UPDATE;
  IF actor_role NOT IN ('owner', 'admin') OR target_role IS NULL THEN
    RAISE EXCEPTION 'membership revocation is not authorized'
      USING ERRCODE = '42501';
  END IF;
  IF actor_role = 'admin' AND target_role IN ('owner', 'admin') THEN
    RAISE EXCEPTION 'only an owner can revoke privileged roles'
      USING ERRCODE = '42501';
  END IF;
  IF target_role = 'owner' AND (
    SELECT count(*) FROM tenant_memberships AS owner_membership
    WHERE owner_membership.tenant_id = p_tenant_id
      AND owner_membership.role = 'owner'
      AND owner_membership.status = 'active'
  ) <= 1 THEN
    RAISE EXCEPTION 'the last tenant owner cannot be revoked'
      USING ERRCODE = '23514';
  END IF;
  UPDATE tenant_memberships AS m
  SET status = 'revoked', revoked_at = now(), updated_at = now()
  WHERE m.tenant_id = p_tenant_id AND m.subject_id = p_target_subject_id;
  RETURN QUERY SELECT p_target_subject_id, target_role, 'revoked';
END
$$;

REVOKE ALL ON FUNCTION tenant_actor_role(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION authorize_identity(UUID, UUID, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_tenant_members(UUID, UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION provision_tenant_member(UUID, UUID, UUID, TEXT, TEXT, TEXT)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION update_tenant_member_role(UUID, UUID, UUID, TEXT)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION revoke_tenant_member(UUID, UUID, UUID) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION authorize_identity(UUID, UUID, TEXT, TEXT)
  TO productivity_app;
GRANT EXECUTE ON FUNCTION list_tenant_members(UUID, UUID) TO productivity_app;
GRANT EXECUTE ON FUNCTION provision_tenant_member(UUID, UUID, UUID, TEXT, TEXT, TEXT)
  TO productivity_app;
GRANT EXECUTE ON FUNCTION update_tenant_member_role(UUID, UUID, UUID, TEXT)
  TO productivity_app;
GRANT EXECUTE ON FUNCTION revoke_tenant_member(UUID, UUID, UUID)
  TO productivity_app;
