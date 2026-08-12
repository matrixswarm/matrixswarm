from __future__ import annotations

def _resolve_deployment_id_for_directive(vault_data, directive_id):
    v = (vault_data or {}).get("vault", {})
    drec = (v.get("directives") or {}).get(directive_id, {}) or {}
    dhash = drec.get("directive_hash") or drec.get("json", {}).get("directive_hash")
    for dep_id, dep in (v.get("deployments") or {}).items():
        if dep.get("directive_hash") == dhash:
            return dep_id
    # fallback: single deployment present
    deps = list((v.get("deployments") or {}).keys())
    return deps[0] if len(deps) == 1 else None

"""
This module resolves agent certs directly from embedded `security-tag`s.
No registry, no versioning. Certs are always local to the deployment.
"""

def resolve_cert_profile_for_deployment(vault_data: dict, deployment_id: str, tagname: str):
    """
    Locate certs for a given deployment and tagname.
    Scans each agent's embedded security-tag for a match.
    """
    deployment = (vault_data or {}).get("deployments", {}).get(deployment_id, {})
    agents = deployment.get("json", {}).get("agents", [])

    for agent in agents:
        for tag in agent.get("tags", []):
            if "security-tag" in tag:
                st = tag["security-tag"]
                if st.get("tag") == tagname:
                    certs = st.get("certs", {})
                    if certs.get("signing") and certs.get("connection"):
                        return certs

    return {}


def resolve_cert_profile_for_directive(vault_data: dict, directive_id: str, tagname: str):
    """
    Alias for resolve_cert_profile_for_deployment, using directives assumed to be deployed.
    """
    return resolve_cert_profile_for_deployment(vault_data, directive_id, tagname)