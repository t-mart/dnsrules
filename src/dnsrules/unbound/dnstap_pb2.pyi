from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SocketFamily(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INET: _ClassVar[SocketFamily]
    INET6: _ClassVar[SocketFamily]

class SocketProtocol(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    UDP: _ClassVar[SocketProtocol]
    TCP: _ClassVar[SocketProtocol]
    DOT: _ClassVar[SocketProtocol]
    DOH: _ClassVar[SocketProtocol]
    DNSCryptUDP: _ClassVar[SocketProtocol]
    DNSCryptTCP: _ClassVar[SocketProtocol]
    DOQ: _ClassVar[SocketProtocol]
INET: SocketFamily
INET6: SocketFamily
UDP: SocketProtocol
TCP: SocketProtocol
DOT: SocketProtocol
DOH: SocketProtocol
DNSCryptUDP: SocketProtocol
DNSCryptTCP: SocketProtocol
DOQ: SocketProtocol

class Dnstap(_message.Message):
    __slots__ = ("identity", "version", "extra", "type", "message")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        MESSAGE: _ClassVar[Dnstap.Type]
    MESSAGE: Dnstap.Type
    IDENTITY_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    identity: bytes
    version: bytes
    extra: bytes
    type: Dnstap.Type
    message: Message
    def __init__(self, identity: _Optional[bytes] = ..., version: _Optional[bytes] = ..., extra: _Optional[bytes] = ..., type: _Optional[_Union[Dnstap.Type, str]] = ..., message: _Optional[_Union[Message, _Mapping]] = ...) -> None: ...

class Policy(_message.Message):
    __slots__ = ("type", "rule", "action", "match", "value")
    class Match(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QNAME: _ClassVar[Policy.Match]
        CLIENT_IP: _ClassVar[Policy.Match]
        RESPONSE_IP: _ClassVar[Policy.Match]
        NS_NAME: _ClassVar[Policy.Match]
        NS_IP: _ClassVar[Policy.Match]
    QNAME: Policy.Match
    CLIENT_IP: Policy.Match
    RESPONSE_IP: Policy.Match
    NS_NAME: Policy.Match
    NS_IP: Policy.Match
    class Action(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        NXDOMAIN: _ClassVar[Policy.Action]
        NODATA: _ClassVar[Policy.Action]
        PASS: _ClassVar[Policy.Action]
        DROP: _ClassVar[Policy.Action]
        TRUNCATE: _ClassVar[Policy.Action]
        LOCAL_DATA: _ClassVar[Policy.Action]
    NXDOMAIN: Policy.Action
    NODATA: Policy.Action
    PASS: Policy.Action
    DROP: Policy.Action
    TRUNCATE: Policy.Action
    LOCAL_DATA: Policy.Action
    TYPE_FIELD_NUMBER: _ClassVar[int]
    RULE_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    MATCH_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    type: str
    rule: bytes
    action: Policy.Action
    match: Policy.Match
    value: bytes
    def __init__(self, type: _Optional[str] = ..., rule: _Optional[bytes] = ..., action: _Optional[_Union[Policy.Action, str]] = ..., match: _Optional[_Union[Policy.Match, str]] = ..., value: _Optional[bytes] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("type", "socket_family", "socket_protocol", "query_address", "response_address", "query_port", "response_port", "query_time_sec", "query_time_nsec", "query_message", "query_zone", "response_time_sec", "response_time_nsec", "response_message", "policy")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        AUTH_QUERY: _ClassVar[Message.Type]
        AUTH_RESPONSE: _ClassVar[Message.Type]
        RESOLVER_QUERY: _ClassVar[Message.Type]
        RESOLVER_RESPONSE: _ClassVar[Message.Type]
        CLIENT_QUERY: _ClassVar[Message.Type]
        CLIENT_RESPONSE: _ClassVar[Message.Type]
        FORWARDER_QUERY: _ClassVar[Message.Type]
        FORWARDER_RESPONSE: _ClassVar[Message.Type]
        STUB_QUERY: _ClassVar[Message.Type]
        STUB_RESPONSE: _ClassVar[Message.Type]
        TOOL_QUERY: _ClassVar[Message.Type]
        TOOL_RESPONSE: _ClassVar[Message.Type]
        UPDATE_QUERY: _ClassVar[Message.Type]
        UPDATE_RESPONSE: _ClassVar[Message.Type]
    AUTH_QUERY: Message.Type
    AUTH_RESPONSE: Message.Type
    RESOLVER_QUERY: Message.Type
    RESOLVER_RESPONSE: Message.Type
    CLIENT_QUERY: Message.Type
    CLIENT_RESPONSE: Message.Type
    FORWARDER_QUERY: Message.Type
    FORWARDER_RESPONSE: Message.Type
    STUB_QUERY: Message.Type
    STUB_RESPONSE: Message.Type
    TOOL_QUERY: Message.Type
    TOOL_RESPONSE: Message.Type
    UPDATE_QUERY: Message.Type
    UPDATE_RESPONSE: Message.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    SOCKET_FAMILY_FIELD_NUMBER: _ClassVar[int]
    SOCKET_PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    QUERY_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    QUERY_PORT_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_PORT_FIELD_NUMBER: _ClassVar[int]
    QUERY_TIME_SEC_FIELD_NUMBER: _ClassVar[int]
    QUERY_TIME_NSEC_FIELD_NUMBER: _ClassVar[int]
    QUERY_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    QUERY_ZONE_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_TIME_SEC_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_TIME_NSEC_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    POLICY_FIELD_NUMBER: _ClassVar[int]
    type: Message.Type
    socket_family: SocketFamily
    socket_protocol: SocketProtocol
    query_address: bytes
    response_address: bytes
    query_port: int
    response_port: int
    query_time_sec: int
    query_time_nsec: int
    query_message: bytes
    query_zone: bytes
    response_time_sec: int
    response_time_nsec: int
    response_message: bytes
    policy: Policy
    def __init__(self, type: _Optional[_Union[Message.Type, str]] = ..., socket_family: _Optional[_Union[SocketFamily, str]] = ..., socket_protocol: _Optional[_Union[SocketProtocol, str]] = ..., query_address: _Optional[bytes] = ..., response_address: _Optional[bytes] = ..., query_port: _Optional[int] = ..., response_port: _Optional[int] = ..., query_time_sec: _Optional[int] = ..., query_time_nsec: _Optional[int] = ..., query_message: _Optional[bytes] = ..., query_zone: _Optional[bytes] = ..., response_time_sec: _Optional[int] = ..., response_time_nsec: _Optional[int] = ..., response_message: _Optional[bytes] = ..., policy: _Optional[_Union[Policy, _Mapping]] = ...) -> None: ...
