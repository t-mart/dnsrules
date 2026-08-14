"""Print the answer flags that dnstap carries, for one query at a time.

Run it next to `just unbound`, then dig through that resolver. Use it to settle
a question about what the resolver actually says, rather than reason about it.

    uv run python dev/probe.py
"""

import sys

import dns.flags
import dns.message
import dns.rcode

sys.path.insert(0, "src")

from dnsrules.unbound import dnstap_pb2, framestream, receiver


def describe(payload: bytes) -> str | None:
    tap = dnstap_pb2.Dnstap()
    tap.ParseFromString(payload)
    message = tap.message
    if message.type != dnstap_pb2.Message.CLIENT_RESPONSE:
        return None
    answer = dns.message.from_wire(
        message.response_message, question_only=True, ignore_trailing=True
    )
    question = answer.question[0]
    return (
        f"{question.name.to_text(omit_final_dot=True):<28} "
        f"{dns.rcode.to_text(answer.rcode()):<9} "
        f"flags={dns.flags.to_text(answer.flags):<12} "
        f"answers={len(answer.answer)}"
    )


def main() -> None:
    print("name                         rcode     flags        answers")
    for chunks in receiver.connections("0.0.0.0", 6000):
        for frame in framestream.read(chunks):
            try:
                line = describe(frame)
            except Exception as problem:
                print(f"undecodable: {problem}")
                continue
            if line:
                print(line, flush=True)


if __name__ == "__main__":
    main()
