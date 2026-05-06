"""Groq-powered LLM service with OpenAI-compatible tool-use agentic loop."""
import json
import logging

from groq import AsyncGroq
from sqlalchemy.ext.asyncio import AsyncSession

from agent.prompts import SYSTEM_PROMPT
from agent.session import CallSession
from agent.tools import TOOLS, execute_tool
from config import settings

logger = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _client


async def get_response(session: CallSession, user_message: str, db: AsyncSession) -> str:
    """
    Append user_message to session history, run the Groq agentic loop
    (handling tool calls until stop), and return the final text response.

    Conversation history uses OpenAI message format:
      {"role": "user"|"assistant"|"tool", "content": "..."}
    Tool-call turns additionally carry "tool_calls" on the assistant message
    and "tool_call_id" on the tool result message.
    """
    client = _get_client()
    session.conversation_history.append({"role": "user", "content": user_message})

    max_iterations = 5
    for _ in range(max_iterations):
        response = await client.chat.completions.create(
            model=settings.GROQ_MODEL,
            max_tokens=512,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *session.conversation_history,
            ],
            tools=TOOLS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason

        # ── Plain text response ──────────────────────────────────────────────
        if finish_reason == "stop" or not message.tool_calls:
            text = message.content or ""
            session.conversation_history.append({"role": "assistant", "content": text})
            return text

        # ── Tool-call response ───────────────────────────────────────────────
        if finish_reason == "tool_calls":
            # Record the assistant turn (with tool_calls) in history
            session.conversation_history.append({
                "role": "assistant",
                "content": message.content,  # may be None
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            # Execute each tool and record results
            for tc in message.tool_calls:
                logger.info("[Tool] %s %s", tc.function.name, tc.function.arguments[:120])
                args = json.loads(tc.function.arguments)
                result_json = await execute_tool(tc.function.name, args, db)
                logger.info("[Tool result] %s", result_json[:200])
                session.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_json,
                })
            continue  # send tool results back to Groq

        break  # unexpected finish_reason

    fallback = "I'm sorry, I ran into a technical issue. Let me connect you with a team member."
    session.conversation_history.append({"role": "assistant", "content": fallback})
    return fallback
