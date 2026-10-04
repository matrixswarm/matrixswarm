"""Operator-approved actions. Approval is deliberately absent from the RPC surface."""
from copy import deepcopy
import hashlib
import json
import time
from .permissions import validate_changes
from .deployment_view import configured_agent, update_sealed_config


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AssignmentActions:
    def _action_context(self, method, params):
        session = None
        if method == "agent.restart":
            session = self._session(params["session_id"])
            if session.get("proc") is None or not session["proc"].is_alive():
                raise ValueError("Phoenix session is not running. Connect before requesting a restart.")
            deployment_id = str(session.get("deployment_id", session["session_id"]))
            deployment_id, deployment = self._resolve_deployment(deployment_id)
        else:
            deployment_id, deployment = self._resolve_deployment(params["deployment_id"])
        if "agent_id" in params:
            self._agent(deployment_id, params["agent_id"])
            if method == "agent.config.set":
                validate_changes(configured_agent(deployment, params["agent_id"]), params["changes"])
        return deployment_id, deployment, session

    def request_action(self, method, params):
        self._require_assignment()
        request_id = params["request_id"]
        existing = self._actions.get(request_id)
        if existing:
            if existing["method"] != method or existing["params"] != params:
                raise ValueError("request_id already belongs to a different action.")
            return self.action_status(request_id)
        self._expire_actions()
        if len(self._actions) >= 256 or sum(a["state"] == "pending" for a in self._actions.values()) >= 8:
            raise ValueError("Assignment action limit reached. Ask the operator to review pending actions or reopen the assignment.")
        dep_id, deployment, session = self._action_context(method, params)
        self._actions[request_id] = {
            "request_id": request_id, "method": method, "params": deepcopy(params),
            "deployment_id": dep_id, "fingerprint": fingerprint(deployment),
            "session": session, "connection": session.get("conn") if session else None,
            "state": "pending", "deadline": time.monotonic() + 120,
            "assignment_id": self._assignment_id,
        }
        return self.action_status(request_id)

    def _expire_actions(self):
        for action in self._actions.values():
            if action["state"] == "pending" and time.monotonic() >= action["deadline"]:
                action["state"] = "expired"
                action["session"] = action["connection"] = None

    def action_status(self, request_id):
        self._require_assignment()
        self._expire_actions()
        action = self._actions.get(request_id)
        if action is None:
            raise ValueError("Action not found in this assignment.")
        result = {key: deepcopy(action[key]) for key in ("request_id", "method", "state", "deployment_id")}
        if "result" in action:
            result["result"] = deepcopy(action["result"])
        result["hint"] = ("Waiting for the operator in Phoenix; expires after 120 seconds."
                          if action["state"] == "pending"
                          else "Inspect this result before issuing any new action.")
        return result

    def pending_approval(self):
        """Called only by the operator UI, never exposed through handle()."""
        if not self._assignment_id:
            return None
        self._expire_actions()
        for action in self._actions.values():
            if action["state"] == "pending":
                params = action["params"]
                effect = {
                    "deployment.launch": "Open a Phoenix connection session. Does not boot a universe.",
                    "agent.restart": "Restart this one agent. Its current work may be interrupted. Descendants are not requested.",
                    "agent.config.set": "Save only the listed settings in the encrypted deployment vault. Running agents are unchanged.",
                }[action["method"]]
                return {
                    "assignment_id": self._assignment_id, "request_id": action["request_id"],
                    "text": f"Terminal requested: {action['method']}\n"
                            f"Deployment: {action['deployment_id']}\n"
                            f"Agent: {params.get('agent_id', '(deployment)')}\n"
                            f"Changes: {json.dumps(params.get('changes', {}), sort_keys=True)}\n\n"
                            f"{effect}\n\nApprove this exact request once?",
                }
        return None

    def resolve_action(self, request_id, approved, assignment_id):
        """Operator-only entry point; bound to the assignment shown in the prompt."""
        if not self._assignment_id or assignment_id != self._assignment_id:
            return
        self._expire_actions()
        action = self._actions.get(request_id)
        if action is None or action["state"] != "pending":
            return
        if approved is not True:
            action["state"] = "denied"
            action["session"] = action["connection"] = None
            return
        try:
            self._require_assignment()
            dep_id, deployment, session = self._action_context(action["method"], action["params"])
            if fingerprint(deployment) != action["fingerprint"]:
                action["state"] = "stale"
                return
            if session is not action["session"] or (session and session.get("conn") is not action["connection"]):
                action["state"] = "stale"
                return
            action["state"] = "executing"  # Consume before any nested Qt event loop.
            if action["method"] == "deployment.launch":
                action["result"] = self._open_deployment(dep_id, deepcopy(deployment))
                action["state"] = action["result"]["state"]
            elif action["method"] == "agent.config.set":
                def transform(deployments):
                    current = deployments.get(dep_id)
                    if fingerprint(current) != action["fingerprint"]:
                        raise ValueError("Deployment changed before save.")
                    update_sealed_config(current, action["params"]["agent_id"], action["params"]["changes"])
                    return deployments
                if not self._vault().transform_section("deployments", transform):
                    raise RuntimeError("Vault did not acknowledge persistence.")
                action["state"] = "saved"
                action["result"] = {"scope": "saved_deployment", "running_agent_changed": False}
            else:
                action["runtime_session_id"] = session["session_id"]
                session["conn"].send({
                    "type": "bridge.restart", "session_id": session["session_id"],
                    "agent_id": action["params"]["agent_id"], "request_id": request_id,
                })
                action["state"] = "dispatched"
                action["result"] = {"hint": "Sent to the Phoenix session. This is not confirmation that the remote agent restarted."}
        except Exception:
            action["state"] = "uncertain" if action["state"] == "executing" else "stale"
            action["result"] = {"hint": "Check Phoenix and remote state before retrying. No automatic retry was made."}
        finally:
            if action.get("state") != "pending":
                action["session"] = action["connection"] = None
