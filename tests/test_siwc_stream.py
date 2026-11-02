"""ChatGPT-plan stream repair: arguments sent only on `done` reach the tool calls.

The event sequence is the one the route sent for a two-call response (recorded 2026-11-02):
no argument deltas, only `function_call_arguments.done` per call.
"""

from langchain_core.messages import AIMessageChunk
from langchain_openai.chat_models.base import _convert_responses_chunk_to_generation_chunk
from openai.types.responses import (
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
)

from ifdispatcher.siwc import _ArgumentsFromDone


def call(index, city, arguments):
    return ResponseFunctionToolCall.model_construct(
        type="function_call",
        id=f"fc_{index}",
        call_id=f"call_{index}",
        name="lookup",
        arguments=arguments,
        status="completed",
    )


def two_calls_without_deltas():
    for index, city in enumerate(["Paris", "Tokyo"]):
        arguments = f'{{"city": "{city}"}}'
        yield ResponseOutputItemAddedEvent.model_construct(
            type="response.output_item.added",
            output_index=index,
            sequence_number=0,
            item=call(index, city, ""),
        )
        yield ResponseFunctionCallArgumentsDoneEvent.model_construct(
            type="response.function_call_arguments.done",
            output_index=index,
            sequence_number=0,
            item_id=f"fc_{index}",
            arguments=arguments,
        )
        yield ResponseOutputItemDoneEvent.model_construct(
            type="response.output_item.done",
            output_index=index,
            sequence_number=0,
            item=call(index, city, arguments),
        )


class Stream:
    def __init__(self, events):
        self.events = list(events)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def __iter__(self):
        return iter(self.events)


def tool_calls(events):
    message, index, output_index, sub_index = AIMessageChunk(content=[]), -1, -1, -1
    for event in events:
        index, output_index, sub_index, chunk = _convert_responses_chunk_to_generation_chunk(
            event, index, output_index, sub_index, item_output_indices={}
        )
        if chunk:
            message += chunk.message
    return [(c["name"], c["args"]) for c in message.tool_calls]


def test_langchain_alone_drops_arguments_sent_only_on_done():
    assert tool_calls(two_calls_without_deltas()) == [("lookup", {}), ("lookup", {})]


def test_wrapped_stream_keeps_every_calls_arguments():
    with _ArgumentsFromDone(Stream(two_calls_without_deltas())) as stream:
        events = list(stream)
    assert tool_calls(events) == [("lookup", {"city": "Paris"}), ("lookup", {"city": "Tokyo"})]


def test_streamed_deltas_are_not_duplicated():
    delta = ResponseFunctionCallArgumentsDeltaEvent.model_construct(
        type="response.function_call_arguments.delta",
        output_index=0,
        sequence_number=0,
        item_id="fc_0",
        delta='{"city": "Paris"}',
    )
    events = list(two_calls_without_deltas())
    with _ArgumentsFromDone(Stream([events[0], delta, *events[1:3]])) as stream:
        kept = list(stream)
    assert sum(e.type == "response.function_call_arguments.delta" for e in kept) == 1
