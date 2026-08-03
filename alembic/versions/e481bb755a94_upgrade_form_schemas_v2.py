"""
upgrade form schemas v2

Revision ID: e481bb755a94
Revises: 21844f9eb716
Create Date: 2026-07-30 15:53:05.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import json

# revision identifiers, used by Alembic.
revision: str = 'e481bb755a94'
down_revision: Union[str, None] = '21844f9eb716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    v2_schema = [
        {"name": "name", "label": "Full Name", "type": "text", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "phone", "label": "Mobile Phone Number", "type": "tel", "required": True},
        {"name": "branch", "label": "Program / Branch of Interest", "type": "dropdown", "required": True},
        {"name": "country", "label": "Country of Residence", "type": "text", "required": False},
        {"name": "nationality", "label": "Nationality", "type": "text", "required": False},
        {"name": "education_level", "label": "Current Education Level", "type": "dropdown", "required": False, "options": ["High School", "Bachelor's", "Master's", "Other"]},
        {"name": "current_school", "label": "Current School / University", "type": "text", "required": False},
        {"name": "preferred_intake", "label": "Preferred Intake", "type": "dropdown", "required": False, "options": ["Fall", "Spring", "Summer"]},
        {"name": "preferred_contact", "label": "Preferred Contact Method", "type": "dropdown", "required": False, "options": ["Email", "Phone", "WhatsApp"]},
        {"name": "additional_comments", "label": "Additional Questions or Comments", "type": "textarea", "required": False}
    ]
    
    # 1. Update existing organizations to use the V2 schema
    v2_json_str = json.dumps(v2_schema).replace("'", "''")
    op.execute(f"""
        UPDATE form_schemas 
        SET fields = '{v2_json_str}'::jsonb;
    """)

    # 2. Update auth.create_organization to automatically provision form_schemas and a default stand/card for new orgs
    # Note: Currently form_schemas wasn't provisioned automatically in this function. We will add it now.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION auth.create_organization(
            p_name           TEXT,
            p_billing_status TEXT DEFAULT 'active',
            p_admin_email    TEXT DEFAULT NULL,
            p_admin_role     TEXT DEFAULT 'owner'
        )
        RETURNS TABLE (org_id UUID, admin_user_id UUID)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            v_org_id  UUID;
            v_user_id UUID;
        BEGIN
            INSERT INTO organizations (name, billing_status)
            VALUES (p_name, p_billing_status)
            RETURNING id INTO v_org_id;

            IF p_admin_email IS NOT NULL THEN
                INSERT INTO staff_users (org_id, email, role)
                VALUES (v_org_id, p_admin_email, p_admin_role)
                RETURNING id INTO v_user_id;
            END IF;

            -- Provision default V2 form schema
            INSERT INTO form_schemas (org_id, fields)
            VALUES (v_org_id, '{v2_json_str}'::jsonb);

            RETURN QUERY SELECT v_org_id, v_user_id;
        END;
        $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tapply_app') THEN
                GRANT EXECUTE ON FUNCTION auth.create_organization(text, text, text, text) TO tapply_app;
            END IF;
        END
        $$
    """)

def downgrade() -> None:
    v1_schema = [
        {"name": "name", "label": "Full Name", "type": "text", "required": True},
        {"name": "email", "label": "Email Address", "type": "email", "required": True},
        {"name": "phone", "label": "Phone Number", "type": "tel", "required": True},
        {"name": "branch", "label": "Program / Branch", "type": "dropdown", "required": True}
    ]
    
    op.execute(f"""
        UPDATE form_schemas 
        SET fields = '{json.dumps(v1_schema)}'::jsonb;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION auth.create_organization(
            p_name           TEXT,
            p_billing_status TEXT DEFAULT 'active',
            p_admin_email    TEXT DEFAULT NULL,
            p_admin_role     TEXT DEFAULT 'owner'
        )
        RETURNS TABLE (org_id UUID, admin_user_id UUID)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            v_org_id  UUID;
            v_user_id UUID;
        BEGIN
            INSERT INTO organizations (name, billing_status)
            VALUES (p_name, p_billing_status)
            RETURNING id INTO v_org_id;

            IF p_admin_email IS NOT NULL THEN
                INSERT INTO staff_users (org_id, email, role)
                VALUES (v_org_id, p_admin_email, p_admin_role)
                RETURNING id INTO v_user_id;
            END IF;

            RETURN QUERY SELECT v_org_id, v_user_id;
        END;
        $$
    """)
