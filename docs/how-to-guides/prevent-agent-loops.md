# Prevent Agent Loops

This guide shows how to detect and prevent infinite loops in Agent execution.

## The Problem

Agents can get stuck in infinite loops when:

- Tools return ambiguous results
- Agent misinterprets responses
- Circular dependencies between tools
- Poor prompt engineering

## Loop Detection

### Max Iterations Limit

```python
from onion_core.agent import AgentLoop

class SafeAgentLoop(AgentLoop):
    """Agent loop with iteration limits."""
    
    def __init__(self, max_iterations=10, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_iterations = max_iterations
        self.current_iteration = 0
    
    async def run(self, prompt: str):
        """Run agent with loop protection."""
        self.current_iteration = 0
        
        while self.current_iteration < self.max_iterations:
            self.current_iteration += 1
            
            # Execute one iteration
            result = await self.step()
            
            if result.is_complete:
                return result
        
        raise AgentLoopError(
            f"Agent exceeded maximum iterations ({self.max_iterations})"
        )
```

### Pattern Detection

Detect repetitive patterns:

```python
from collections import Counter

class LoopDetector:
    """Detect looping patterns in agent execution."""
    
    def __init__(self, window_size=5, threshold=0.8):
        self.window_size = window_size
        self.threshold = threshold
        self.history = []
    
    def add_step(self, action: str, tool_name: str):
        """Record agent step."""
        self.history.append({
            'action': action,
            'tool': tool_name,
            'timestamp': time.time()
        })
        
        # Keep only recent history
        if len(self.history) > self.window_size * 2:
            self.history = self.history[-self.window_size * 2:]
    
    def is_looping(self) -> bool:
        """Check if agent is in a loop."""
        if len(self.history) < self.window_size:
            return False
        
        # Check recent actions
        recent = self.history[-self.window_size:]
        
        # Count tool usage
        tool_counts = Counter(step['tool'] for step in recent)
        
        # If same tool used > threshold% of time, likely looping
        most_common_count = tool_counts.most_common(1)[0][1]
        ratio = most_common_count / len(recent)
        
        return ratio > self.threshold
    
    def get_loop_info(self) -> dict:
        """Get information about detected loop."""
        recent = self.history[-self.window_size:]
        tool_counts = Counter(step['tool'] for step in recent)
        
        return {
            'dominant_tool': tool_counts.most_common(1)[0][0],
            'repetition_ratio': tool_counts.most_common(1)[0][1] / len(recent),
            'steps_analyzed': len(recent)
        }
```

## Prevention Strategies

### Diverse Action Enforcement

```python
class DiversityEnforcer:
    """Ensure agent takes diverse actions."""
    
    def __init__(self, min_diversity=0.3):
        self.min_diversity = min_diversity
        self.recent_actions = []
    
    def should_continue(self, action: str) -> bool:
        """Check if action maintains diversity."""
        self.recent_actions.append(action)
        
        if len(self.recent_actions) < 5:
            return True
        
        # Keep last 10 actions
        self.recent_actions = self.recent_actions[-10:]
        
        # Calculate diversity
        unique_actions = len(set(self.recent_actions))
        diversity = unique_actions / len(self.recent_actions)
        
        return diversity >= self.min_diversity
    
    def suggest_alternative(self) -> str:
        """Suggest alternative action when stuck."""
        return "Consider using a different approach or tool"
```

### Timeout Protection

```python
import asyncio

async def run_with_timeout(agent, prompt, timeout=60):
    """Run agent with timeout protection."""
    try:
        return await asyncio.wait_for(
            agent.run_async(prompt),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(f"Agent timed out after {timeout}s")
        raise AgentTimeoutError("Agent execution timed out")
```

### State Tracking

```python
class AgentStateTracker:
    """Track agent state to detect stagnation."""
    
    def __init__(self):
        self.states = []
    
    def record_state(self, state: dict):
        """Record agent state."""
        self.states.append({
            'state': state,
            'timestamp': time.time()
        })
        
        # Keep last 20 states
        if len(self.states) > 20:
            self.states = self.states[-20:]
    
    def is_stagnant(self) -> bool:
        """Check if agent state is not progressing."""
        if len(self.states) < 5:
            return False
        
        recent_states = self.states[-5:]
        
        # Check if state hasn't changed
        first_state = recent_states[0]['state']
        for state_entry in recent_states[1:]:
            if state_entry['state'] != first_state:
                return False
        
        return True
```

## Recovery Mechanisms

### Automatic Recovery

```python
class LoopRecovery:
    """Recover from detected loops."""
    
    def __init__(self, agent_loop):
        self.agent_loop = agent_loop
        self.recovery_attempts = 0
    
    def on_loop_detected(self):
        """Handle loop detection."""
        self.recovery_attempts += 1
        
        if self.recovery_attempts == 1:
            # First attempt: Add guidance
            self.agent_loop.add_system_message(
                "You seem to be repeating the same action. "
                "Try a different approach."
            )
        
        elif self.recovery_attempts == 2:
            # Second attempt: Force different tool
            self.agent_loop.force_tool_change()
        
        else:
            # Third attempt: Give up
            raise AgentLoopError(
                "Agent stuck in loop despite recovery attempts"
            )
```

### Manual Intervention

```python
def provide_human_guidance(agent_loop, context: str):
    """Allow human to provide guidance when loop detected."""
    
    guidance = input(
        f"Agent appears stuck. Context: {context}\n"
        "Provide guidance (or press Enter to abort): "
    )
    
    if guidance:
        agent_loop.add_user_message(guidance)
        return True
    else:
        return False
```

## Integration with Pipeline

### Complete Solution

```python
from onion_core.base import BaseMiddleware

class LoopProtectionMiddleware(BaseMiddleware):
    """Comprehensive loop protection."""
    
    def __init__(self, max_iterations=10):
        self.max_iterations = max_iterations
        self.loop_detector = LoopDetector()
        self.state_tracker = AgentStateTracker()
    
    async def process_request(self, request):
        """Monitor and protect against loops."""
        
        # Record this step
        self.loop_detector.add_step(
            request.action,
            request.tool_name if hasattr(request, 'tool_name') else None
        )
        
        # Check for loops
        if self.loop_detector.is_looping():
            loop_info = self.loop_detector.get_loop_info()
            logger.warning(f"Potential loop detected: {loop_info}")
            
            # Take corrective action
            request.system_prompt += (
                "\n\nWARNING: You appear to be repeating the same action. "
                "Please try a different approach."
            )
        
        # Check state stagnation
        self.state_tracker.record_state(request.state)
        if self.state_tracker.is_stagnant():
            logger.warning("Agent state is stagnant")
        
        # Continue processing
        return await self.next.process_request(request)
```

## Monitoring

### Track Loop Metrics

```python
from onion_core.observability import MetricsCollector

metrics = MetricsCollector()

def track_loop_metrics(iterations: int, loop_detected: bool):
    """Track agent loop metrics."""
    
    metrics.histogram('agent.iterations', iterations)
    
    if loop_detected:
        metrics.increment('agent.loops.detected')
    
    if iterations > 8:  # Close to max
        metrics.increment('agent.near_max_iterations')
```

## Best Practices

1. **Set Reasonable Limits**: 10-20 iterations max
2. **Monitor Closely**: Track iteration counts
3. **Provide Guidance**: Help agents escape loops
4. **Use Multiple Detection Methods**: Combine strategies
5. **Log Loop Events**: For debugging and improvement
6. **Test Edge Cases**: Verify loop detection works

## Related Topics

- [Implement Tool Deduplication](implement-tool-deduplication.md)
- [Agent State Machine](../explanation/agent-state-machine.md)
- [Troubleshoot Timeouts](troubleshoot-timeouts.md)
