import os
import json

POD_DIR = "/sites/orbit/python/pod"
COMM_DIR = "/sites/orbit/python/comm"


def list_pods():
    print("\n🧠 ACTIVE PODS:")
    if not os.path.exists(POD_DIR):
        print(" - No pods directory found. Matrix may be idle.")
        return
    for uuid in os.listdir(POD_DIR):
        uuid_path = os.path.join(POD_DIR, uuid)
        if os.path.isdir(uuid_path):
            print(f" - UUID: {uuid}")


def list_comm():
    print("\n🧠 REGISTERED PERMANENT IDs:")
    if not os.path.exists(COMM_DIR):
        print(" - No comm directory found.")
        return
    for perm_id in os.listdir(COMM_DIR):
        perm_path = os.path.join(COMM_DIR, perm_id)
        if os.path.isdir(perm_path):
            print(f" - perm_id: {perm_id}")


def main():
    print("\n📋 MATRIX AGENT LISTING\n========================")
    list_pods()
    list_comm()
    print("\nDone.\n")


if __name__ == "__main__":
    main()
