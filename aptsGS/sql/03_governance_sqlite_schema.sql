-- Governance SQLite schema v1; structure only, no operational records.
CREATE TABLE "gov_approval_decisions" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"approval_decision_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("approval_decision_id")<=100),"approval_request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("approval_request_id")<=100),"approver_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("approver_id")<=255),"approver_role" TEXT COLLATE NOCASE NOT NULL CHECK (length("approver_role")<=100),"decision" TEXT COLLATE NOCASE NOT NULL CHECK ("decision" IN ('APPROVE','DENY')),"reason" TEXT NOT NULL,"decision_hash" TEXT COLLATE NOCASE NOT NULL CHECK (length("decision_hash")<=64),"decided_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_approval_decision_request" FOREIGN KEY ("approval_request_id") REFERENCES "gov_approval_requests" ("approval_request_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE TABLE "gov_approval_requests" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"approval_request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("approval_request_id")<=100),"authorization_request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("authorization_request_id")<=100),"mission_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("mission_id")<=100),"risk_level" TEXT COLLATE NOCASE NOT NULL CHECK ("risk_level" IN ('LOW','MODERATE','HIGH','CRITICAL')),"reason" TEXT NOT NULL,"required_approver_role" TEXT COLLATE NOCASE NOT NULL DEFAULT 'SECURITY_APPROVER' CHECK (length("required_approver_role")<=100),"status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'PENDING' CHECK ("status" IN ('PENDING','APPROVED','DENIED','EXPIRED','CANCELLED')),"expires_at" DATETIME DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_approval_authorization" FOREIGN KEY ("authorization_request_id") REFERENCES "gov_authorization_requests" ("request_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE TABLE "gov_audit_log" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"audit_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("audit_id")<=100),"event_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("event_type")<=100),"actor_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("actor_id")<=255),"mission_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("mission_id")<=100),"subject_type" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("subject_type")<=100),"subject_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("subject_id")<=255),"payload_json" TEXT DEFAULT NULL,"previous_hash" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("previous_hash")<=64),"record_hash" TEXT COLLATE NOCASE NOT NULL CHECK (length("record_hash")<=64),"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE "gov_authorization_requests" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("request_id")<=100),"mission_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("mission_id")<=100),"scope_contract_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("scope_contract_id")<=100),"subject_component" TEXT COLLATE NOCASE NOT NULL CHECK (length("subject_component")<=255),"action_class" TEXT COLLATE NOCASE NOT NULL CHECK (length("action_class")<=100),"action_name" TEXT COLLATE NOCASE NOT NULL CHECK (length("action_name")<=255),"resource_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("resource_type")<=100),"resource_value" TEXT COLLATE NOCASE NOT NULL CHECK (length("resource_value")<=1000),"context_json" TEXT DEFAULT NULL,"evidence_refs_json" TEXT DEFAULT NULL,"requested_by" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("requested_by")<=255),"request_status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'EVALUATING' CHECK ("request_status" IN ('EVALUATING','ALLOW','DENY','REVIEW','CANCELLED')),"requested_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_authorization_scope" FOREIGN KEY ("scope_contract_id") REFERENCES "gov_scope_contracts" ("scope_contract_id") ON UPDATE CASCADE ON DELETE SET NULL);

CREATE TABLE "gov_compliance_obligations" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"obligation_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("obligation_id")<=100),"policy_set_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("policy_set_id")<=100),"action_class" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("action_class")<=100),"obligation_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("obligation_type")<=100),"description" TEXT NOT NULL,"mandatory" INTEGER NOT NULL DEFAULT 1 CHECK ("mandatory" IN (0,1)),"config_json" TEXT DEFAULT NULL,"enabled" INTEGER NOT NULL DEFAULT 1 CHECK ("enabled" IN (0,1)),"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_compliance_policy" FOREIGN KEY ("policy_set_id") REFERENCES "gov_policy_sets" ("policy_set_id") ON UPDATE CASCADE ON DELETE RESTRICT);

CREATE TABLE "gov_emergency_actions" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"action_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("action_id")<=100),"action_type" TEXT COLLATE NOCASE NOT NULL CHECK ("action_type" IN ('ACTIVATE','RELEASE')),"actor_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("actor_id")<=255),"reason" TEXT NOT NULL,"metadata_json" TEXT DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE "gov_emergency_state" ("singleton_id" INTEGER NOT NULL CHECK ("singleton_id">=0),"active" INTEGER NOT NULL DEFAULT 0 CHECK ("active" IN (0,1)),"reason" TEXT DEFAULT NULL,"version" INTEGER NOT NULL DEFAULT 0 CHECK ("version">=0),"activated_by" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("activated_by")<=255),"activated_at" DATETIME DEFAULT NULL,"released_by" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("released_by")<=255),"released_at" DATETIME DEFAULT NULL,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY ("singleton_id"));

CREATE TABLE "gov_event_outbox" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"event_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("event_id")<=100),"mission_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("mission_id")<=100),"event_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("event_type")<=100),"source_component" TEXT COLLATE NOCASE NOT NULL DEFAULT 'GOV-PLANE' CHECK (length("source_component")<=100),"severity" TEXT COLLATE NOCASE NOT NULL DEFAULT 'INFO' CHECK (length("severity")<=20),"payload_json" TEXT NOT NULL,"delivery_status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'PENDING' CHECK ("delivery_status" IN ('PENDING','DELIVERED','FAILED')),"attempt_count" INTEGER NOT NULL DEFAULT 0,"last_error" TEXT DEFAULT NULL,"next_attempt_at" DATETIME DEFAULT NULL,"delivered_at" DATETIME DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE "gov_policy_decisions" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"decision_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("decision_id")<=100),"request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("request_id")<=100),"mission_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("mission_id")<=100),"policy_set_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("policy_set_id")<=100),"policy_version" INTEGER DEFAULT NULL,"scope_contract_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("scope_contract_id")<=100),"scope_version" INTEGER DEFAULT NULL,"decision" TEXT COLLATE NOCASE NOT NULL CHECK ("decision" IN ('ALLOW','DENY','REVIEW')),"reason_codes_json" TEXT NOT NULL,"constraints_json" TEXT DEFAULT NULL,"requires_human_approval" INTEGER NOT NULL DEFAULT 0 CHECK ("requires_human_approval" IN (0,1)),"approval_request_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("approval_request_id")<=100),"valid_from" DATETIME NOT NULL,"valid_until" DATETIME NOT NULL,"decision_hash" TEXT COLLATE NOCASE NOT NULL CHECK (length("decision_hash")<=64),"supersedes_decision_id" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("supersedes_decision_id")<=100),"decision_status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'ACTIVE' CHECK ("decision_status" IN ('ACTIVE','REVOKED','EXPIRED','SUPERSEDED')),"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_policy_decision_approval" FOREIGN KEY ("approval_request_id") REFERENCES "gov_approval_requests" ("approval_request_id") ON UPDATE CASCADE ON DELETE SET NULL,CONSTRAINT "fk_gov_policy_decision_request" FOREIGN KEY ("request_id") REFERENCES "gov_authorization_requests" ("request_id") ON UPDATE CASCADE ON DELETE CASCADE,CONSTRAINT "fk_gov_policy_decision_scope" FOREIGN KEY ("scope_contract_id") REFERENCES "gov_scope_contracts" ("scope_contract_id") ON UPDATE CASCADE ON DELETE SET NULL);

CREATE TABLE "gov_policy_rules" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"rule_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("rule_id")<=100),"policy_set_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("policy_set_id")<=100),"priority" INTEGER NOT NULL DEFAULT 100,"rule_name" TEXT COLLATE NOCASE NOT NULL CHECK (length("rule_name")<=255),"rule_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("rule_type")<=100),"effect" TEXT COLLATE NOCASE NOT NULL CHECK ("effect" IN ('ALLOW','DENY','REVIEW')),"action_class" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("action_class")<=100),"condition_json" TEXT DEFAULT NULL,"obligations_json" TEXT DEFAULT NULL,"enabled" INTEGER NOT NULL DEFAULT 1 CHECK ("enabled" IN (0,1)),"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_policy_rules_set" FOREIGN KEY ("policy_set_id") REFERENCES "gov_policy_sets" ("policy_set_id") ON UPDATE CASCADE ON DELETE RESTRICT);

CREATE TABLE "gov_policy_sets" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"policy_set_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("policy_set_id")<=100),"name" TEXT COLLATE NOCASE NOT NULL CHECK (length("name")<=255),"version" INTEGER NOT NULL DEFAULT 1,"status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'DRAFT' CHECK ("status" IN ('DRAFT','ACTIVE','RETIRED')),"default_effect" TEXT COLLATE NOCASE NOT NULL DEFAULT 'DENY' CHECK ("default_effect" IN ('DENY','REVIEW')),"effective_from" DATETIME DEFAULT NULL,"effective_until" DATETIME DEFAULT NULL,"description" TEXT DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE "gov_risk_assessments" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"assessment_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("assessment_id")<=100),"request_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("request_id")<=100),"mission_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("mission_id")<=100),"risk_score" DECIMAL_TEXT NOT NULL,"risk_level" TEXT COLLATE NOCASE NOT NULL CHECK ("risk_level" IN ('LOW','MODERATE','HIGH','CRITICAL')),"factors_json" TEXT NOT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_risk_request" FOREIGN KEY ("request_id") REFERENCES "gov_authorization_requests" ("request_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE TABLE "gov_scope_action_constraints" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"constraint_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("constraint_id")<=100),"scope_contract_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_contract_id")<=100),"action_class" TEXT COLLATE NOCASE NOT NULL CHECK (length("action_class")<=100),"action_name" TEXT COLLATE NOCASE NOT NULL DEFAULT '*' CHECK (length("action_name")<=255),"effect" TEXT COLLATE NOCASE NOT NULL DEFAULT 'DENY' CHECK ("effect" IN ('ALLOW','DENY','REVIEW')),"max_risk_level" TEXT COLLATE NOCASE NOT NULL DEFAULT 'LOW' CHECK ("max_risk_level" IN ('LOW','MODERATE','HIGH','CRITICAL')),"requires_approval" INTEGER NOT NULL DEFAULT 0 CHECK ("requires_approval" IN (0,1)),"constraints_json" TEXT DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_action_constraint_contract" FOREIGN KEY ("scope_contract_id") REFERENCES "gov_scope_contracts" ("scope_contract_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE TABLE "gov_scope_contracts" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"scope_contract_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_contract_id")<=100),"mission_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("mission_id")<=100),"name" TEXT COLLATE NOCASE NOT NULL CHECK (length("name")<=255),"status" TEXT COLLATE NOCASE NOT NULL DEFAULT 'DRAFT' CHECK ("status" IN ('DRAFT','ACTIVE','SUSPENDED','EXPIRED','REVOKED')),"policy_set_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("policy_set_id")<=100),"version" INTEGER NOT NULL DEFAULT 1,"valid_from" DATETIME DEFAULT NULL,"valid_until" DATETIME DEFAULT NULL,"created_by" TEXT COLLATE NOCASE NOT NULL CHECK (length("created_by")<=255),"approved_by" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("approved_by")<=255),"approved_at" DATETIME DEFAULT NULL,"metadata_json" TEXT DEFAULT NULL,"contract_hash" TEXT COLLATE NOCASE NOT NULL CHECK (length("contract_hash")<=64),"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_scope_contract_policy" FOREIGN KEY ("policy_set_id") REFERENCES "gov_policy_sets" ("policy_set_id") ON UPDATE CASCADE ON DELETE RESTRICT);

CREATE TABLE "gov_scope_sources" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"scope_source_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_source_id")<=100),"scope_contract_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_contract_id")<=100),"source_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("source_id")<=255),"source_type" TEXT COLLATE NOCASE NOT NULL DEFAULT 'CTI' CHECK (length("source_type")<=100),"allowed" INTEGER NOT NULL DEFAULT 1 CHECK ("allowed" IN (0,1)),"constraints_json" TEXT DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_scope_source_contract" FOREIGN KEY ("scope_contract_id") REFERENCES "gov_scope_contracts" ("scope_contract_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE TABLE "gov_scope_targets" ("id" INTEGER PRIMARY KEY AUTOINCREMENT,"scope_target_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_target_id")<=100),"scope_contract_id" TEXT COLLATE NOCASE NOT NULL CHECK (length("scope_contract_id")<=100),"target_type" TEXT COLLATE NOCASE NOT NULL CHECK (length("target_type")<=50),"target_value" TEXT COLLATE NOCASE NOT NULL CHECK (length("target_value")<=1000),"normalized_value" TEXT COLLATE NOCASE DEFAULT NULL CHECK (length("normalized_value")<=1000),"environment" TEXT COLLATE NOCASE NOT NULL DEFAULT 'LAB' CHECK (length("environment")<=50),"allowed" INTEGER NOT NULL DEFAULT 1 CHECK ("allowed" IN (0,1)),"notes" TEXT DEFAULT NULL,"created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,CONSTRAINT "fk_gov_scope_target_contract" FOREIGN KEY ("scope_contract_id") REFERENCES "gov_scope_contracts" ("scope_contract_id") ON UPDATE CASCADE ON DELETE CASCADE);

CREATE INDEX "gov_approval_decisions__idx_gov_approval_decision_request" ON "gov_approval_decisions" ("approval_request_id","decided_at");

CREATE UNIQUE INDEX "gov_approval_decisions__uq_gov_approval_decision_id" ON "gov_approval_decisions" ("approval_decision_id");

CREATE INDEX "gov_approval_requests__idx_gov_approval_authorization" ON "gov_approval_requests" ("authorization_request_id");

CREATE INDEX "gov_approval_requests__idx_gov_approval_mission" ON "gov_approval_requests" ("mission_id","status","expires_at");

CREATE UNIQUE INDEX "gov_approval_requests__uq_gov_approval_request_id" ON "gov_approval_requests" ("approval_request_id");

CREATE INDEX "gov_audit_log__idx_gov_audit_event" ON "gov_audit_log" ("event_type","created_at");

CREATE INDEX "gov_audit_log__idx_gov_audit_mission" ON "gov_audit_log" ("mission_id","created_at");

CREATE INDEX "gov_audit_log__idx_gov_audit_subject" ON "gov_audit_log" ("subject_type","subject_id","created_at");

CREATE UNIQUE INDEX "gov_audit_log__uq_gov_audit_id" ON "gov_audit_log" ("audit_id");

CREATE INDEX "gov_authorization_requests__idx_gov_authorization_mission" ON "gov_authorization_requests" ("mission_id","request_status","requested_at");

CREATE INDEX "gov_authorization_requests__idx_gov_authorization_scope" ON "gov_authorization_requests" ("scope_contract_id");

CREATE UNIQUE INDEX "gov_authorization_requests__uq_gov_authorization_request_id" ON "gov_authorization_requests" ("request_id");

CREATE INDEX "gov_compliance_obligations__idx_gov_compliance_policy" ON "gov_compliance_obligations" ("policy_set_id","enabled","action_class");

CREATE UNIQUE INDEX "gov_compliance_obligations__uq_gov_compliance_obligation_id" ON "gov_compliance_obligations" ("obligation_id");

CREATE INDEX "gov_emergency_actions__idx_gov_emergency_action_created" ON "gov_emergency_actions" ("created_at");

CREATE UNIQUE INDEX "gov_emergency_actions__uq_gov_emergency_action_id" ON "gov_emergency_actions" ("action_id");

CREATE INDEX "gov_event_outbox__idx_gov_event_outbox_delivery" ON "gov_event_outbox" ("delivery_status","next_attempt_at","id");

CREATE INDEX "gov_event_outbox__idx_gov_event_outbox_mission" ON "gov_event_outbox" ("mission_id","event_type","created_at");

CREATE UNIQUE INDEX "gov_event_outbox__uq_gov_event_outbox_event" ON "gov_event_outbox" ("event_id");

CREATE INDEX "gov_policy_decisions__fk_gov_policy_decision_approval" ON "gov_policy_decisions" ("approval_request_id");

CREATE INDEX "gov_policy_decisions__idx_gov_policy_decision_mission" ON "gov_policy_decisions" ("mission_id","decision_status","valid_until");

CREATE INDEX "gov_policy_decisions__idx_gov_policy_decision_request" ON "gov_policy_decisions" ("request_id","created_at");

CREATE INDEX "gov_policy_decisions__idx_gov_policy_decision_scope" ON "gov_policy_decisions" ("scope_contract_id","decision_status");

CREATE UNIQUE INDEX "gov_policy_decisions__uq_gov_policy_decision_id" ON "gov_policy_decisions" ("decision_id");

CREATE INDEX "gov_policy_rules__idx_gov_policy_rules_set_priority" ON "gov_policy_rules" ("policy_set_id","enabled","priority");

CREATE UNIQUE INDEX "gov_policy_rules__uq_gov_policy_rule_id" ON "gov_policy_rules" ("rule_id");

CREATE INDEX "gov_policy_sets__idx_gov_policy_sets_status" ON "gov_policy_sets" ("status","version");

CREATE UNIQUE INDEX "gov_policy_sets__uq_gov_policy_sets_id" ON "gov_policy_sets" ("policy_set_id");

CREATE INDEX "gov_risk_assessments__idx_gov_risk_mission" ON "gov_risk_assessments" ("mission_id","risk_level","created_at");

CREATE INDEX "gov_risk_assessments__idx_gov_risk_request" ON "gov_risk_assessments" ("request_id");

CREATE UNIQUE INDEX "gov_risk_assessments__uq_gov_risk_assessment_id" ON "gov_risk_assessments" ("assessment_id");

CREATE INDEX "gov_scope_action_constraints__idx_gov_action_constraint_lookup" ON "gov_scope_action_constraints" ("scope_contract_id","action_class","action_name","effect");

CREATE UNIQUE INDEX "gov_scope_action_constraints__uq_gov_action_constraint_id" ON "gov_scope_action_constraints" ("constraint_id");

CREATE INDEX "gov_scope_contracts__fk_gov_scope_contract_policy" ON "gov_scope_contracts" ("policy_set_id");

CREATE INDEX "gov_scope_contracts__idx_gov_scope_contract_mission" ON "gov_scope_contracts" ("mission_id","status","version");

CREATE INDEX "gov_scope_contracts__idx_gov_scope_contract_validity" ON "gov_scope_contracts" ("status","valid_from","valid_until");

CREATE UNIQUE INDEX "gov_scope_contracts__uq_gov_scope_contract_id" ON "gov_scope_contracts" ("scope_contract_id");

CREATE INDEX "gov_scope_sources__idx_gov_scope_source_contract" ON "gov_scope_sources" ("scope_contract_id","allowed");

CREATE INDEX "gov_scope_sources__idx_gov_scope_source_source" ON "gov_scope_sources" ("source_id");

CREATE UNIQUE INDEX "gov_scope_sources__uq_gov_scope_source_id" ON "gov_scope_sources" ("scope_source_id");

CREATE INDEX "gov_scope_targets__idx_gov_scope_target_contract" ON "gov_scope_targets" ("scope_contract_id","allowed");

CREATE INDEX "gov_scope_targets__idx_gov_scope_target_value" ON "gov_scope_targets" ("normalized_value");

CREATE UNIQUE INDEX "gov_scope_targets__uq_gov_scope_target_id" ON "gov_scope_targets" ("scope_target_id");

CREATE TRIGGER "gov_approval_requests__touch_updated_at" AFTER UPDATE ON "gov_approval_requests" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_approval_requests" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_authorization_requests__touch_updated_at" AFTER UPDATE ON "gov_authorization_requests" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_authorization_requests" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_compliance_obligations__touch_updated_at" AFTER UPDATE ON "gov_compliance_obligations" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_compliance_obligations" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_emergency_state__touch_updated_at" AFTER UPDATE ON "gov_emergency_state" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_emergency_state" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "singleton_id"=NEW."singleton_id"; END;

CREATE TRIGGER "gov_event_outbox__touch_updated_at" AFTER UPDATE ON "gov_event_outbox" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_event_outbox" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_policy_decisions__touch_updated_at" AFTER UPDATE ON "gov_policy_decisions" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_policy_decisions" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_policy_rules__touch_updated_at" AFTER UPDATE ON "gov_policy_rules" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_policy_rules" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_policy_sets__touch_updated_at" AFTER UPDATE ON "gov_policy_sets" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_policy_sets" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;

CREATE TRIGGER "gov_scope_contracts__touch_updated_at" AFTER UPDATE ON "gov_scope_contracts" WHEN NEW."updated_at" IS OLD."updated_at" BEGIN UPDATE "gov_scope_contracts" SET "updated_at"=strftime('%Y-%m-%d %H:%M:%f','now') WHERE "id"=NEW."id"; END;
