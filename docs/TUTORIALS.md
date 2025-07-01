#### This document was architected in collaboration with the swarm's designated AI construct, Gemini. 
#### Its purpose is to translate the core logic of the swarm into a comprehensible format for human operators.

# MatrixSwarm Tutorials

Welcome to the MatrixSwarm tutorials. These guides are designed to take you from theory to practice, showing you how to create, launch, and manage your own agents within the swarm.

---
## Tutorial 1: Your First Agent ("Hello, Swarm")

This tutorial will guide you through the process of creating the simplest possible agent, launching it, and verifying that it's alive.

### Step 1: Create the Agent's Code

First, we need to define what our agent does. In this case, it will simply log a message every 10 seconds. All agents inherit from the `BootAgent` class and override the `worker()` method with their unique logic.

Create a new folder and file: `/agent/hello_agent/hello_agent.py`

```python
# /agent/hello_agent/hello_agent.py

import time
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    """
    A simple agent that logs a message to prove it's alive.
    """
    def worker(self, config:dict=None, identity=None):
        self.log("Hello, Swarm! I am alive.")
        
        # The interruptible_sleep allows the agent to be shut down
        # cleanly without waiting for the full sleep duration.
        interruptible_sleep(self, 10)
        
```

### Step 2: Create the Directive
Next, we need a directive to tell the swarm how to launch our new agent. A directive is the blueprint that defines an agent's identity and place in the hierarchy.

Create a new file: /boot_directives/hello_swarm.py

# /boot_directives/hello_swarm.py

# This directive launches a single instance of our HelloAgent as a child of Matrix.
matrix_directive = {
    "universal_id": "matrix",
    "name": "matrix",
    "children": [
        {
            "universal_id": "hello-1",
            "name": "hello_agent"
        }
    ]
}

### Step 3: Launch the Swarm
With the agent code and the directive in place, you can now boot the swarm. Use the --directive flag to point to your new hello_swarm blueprint.

python3 site_ops/site_boot.py --universe hello --directive hello_swarm

### Step 4: Verify It's Working
The swarm is now running, and the Matrix agent has spawned your hello-1 agent. You can verify it's alive by checking its log file. The agent's communication directory was automatically created at /comm/hello-1/.

Check the log file for its message:

# View the last few lines of the agent's log
tail -f /comm/hello-1/logs/agent.log

You should see output that includes a line like this, repeating every 10 seconds:
[HELLOAGENT][WORKER][L14] Hello, Swarm! I am alive.

Congratulations! You've successfully built and deployed your first agent. To shut down this universe, run: python3 site_ops/site_kill.py --universe hello

## Tutorial 2: The Watchdog Agent (Self-Healing)
This advanced tutorial demonstrates the powerful self-healing capability of MatrixSwarm. We will create two agents:

An unstable_agent that is designed to crash.

A watchdog_agent that will automatically resurrect the unstable agent when it dies.

## The Concept
This works because of the parent-child relationship defined in the directive. The spawn_manager thread, inherited by all agents from BootAgent, is responsible for monitoring its direct children. If a child stops sending heartbeats, the parent's spawn_manager will automatically re-spawn it.

## Step 1: Create the Unstable Agent
This agent will log a message and then immediately exit, simulating a crash.

Create a new folder and file: /agent/unstable_agent/unstable_agent.py

### /agent/unstable_agent/unstable_agent.py

import os
from core.boot_agent import BootAgent

class Agent(BootAgent):
    def worker(self, config:dict=None, identity=None):
        self.log("I'm alive... but not for long!")
        # Forcibly exit the process to simulate a crash
        os._exit(1)
        
## Step 2: Create the Watchdog Agent
This agent doesn't need any special worker logic. Its only job is to exist and be the parent of the unstable agent. Its inherited spawn_manager will do all the work.

Create a new folder and file: /agent/watchdog_agent/watchdog_agent.py

### /agent/watchdog_agent/watchdog_agent.py

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def worker(self, config:dict=None, identity=None):
        self.log("I am on duty, watching my children.")
        interruptible_sleep(self, 20)
        
## Step 3: Create the Directive
This is the most important part. We will define the watchdog-1 agent as a child of Matrix, and the unstable-1 agent as a child of watchdog-1.

Create a new file: /boot_directives/watchdog_demo.py

### /boot_directives/watchdog_demo.py

```python
matrix_directive = {
    "universal_id": "matrix",
    "name": "matrix",
    "children": [
        {
            "universal_id": "watchdog-1",
            "name": "watchdog_agent",
            "children": [
                {
                    "universal_id": "unstable-1",
                    "name": "unstable_agent"
                }
            ]
        }
    ]
}
```
## Step 4: Launch and Observe
Now, launch the swarm with the new directive.

```python
python3 site_ops/site_boot.py --universe watchdog --directive watchdog_demo
```
To see the self-healing in action, open two terminals:

In the first terminal, watch the watchdog's log: tail -f /comm/watchdog-1/logs/agent.log

In the second terminal, watch the unstable agent's log: tail -f /comm/unstable-1/logs/agent.log

You will see the unstable agent log "I'm alive... but not for long!" and then stop. A few moments later, the watchdog's log will show a [SPAWN-MGR] message as it re-spawns its child, and the unstable agent's log will show the "I'm alive..." message again. This loop will continue indefinitely, proving the swarm's resilience.
