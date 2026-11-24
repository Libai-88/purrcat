"""表格公式引擎：存公式源码，渲染时算值。

三条硬规则，都是为了不让「算错的数」看起来像「算对的数」：

1. **错误是值，而且会传播。** 引用到的格子里有 `#DIV/0!`，`SUM` 的结果也是 `#DIV/0!`，
   不是「把其余的加起来」。一个被跳过的错误值会悄悄改变结论。
2. **循环引用产生独立的错误值。** 必须是 `#CIRC!` 这种能认出来的错误，不能是 0——
   0 会被当成一个有效测量值混进均值和回归。
3. **易变与外部调用一律拒绝。** `NOW`、`RAND`、`PY`、`WEBSERVICE`、DDE 链接和
   `'[其它工作簿]Sheet'!A1` 都返回 `#NAME?`，因为它们的结果不可复现。

单元格存的是**源码**（`=SUM(A1:A3)` 或 `3`），不是算出来的值。值是渲染时的投影。
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

# 错误值
ERROR_CIRC = "#CIRC!"
ERROR_REF = "#REF!"
ERROR_NAME = "#NAME?"
ERROR_VALUE = "#VALUE!"
ERROR_DIV0 = "#DIV/0!"
ERROR_NUM = "#NUM!"

ERROR_VALUES = (
    ERROR_CIRC,
    ERROR_REF,
    ERROR_NAME,
    ERROR_VALUE,
    ERROR_DIV0,
    ERROR_NUM,
)

# 易变与外部调用：结果不可复现，一律拒绝
DISALLOWED_FUNCTIONS = frozenset(
    {
        "NOW",
        "TODAY",
        "RAND",
        "RANDBETWEEN",
        "PY",
        "PYTHON",
        "WEBSERVICE",
        "FILTERXML",
        "RTD",
        "IMAGE",
        "STOCKHISTORY",
        "IMPORTDATA",
        "IMPORTXML",
        "IMPORTHTML",
        "IMPORTFEED",
        "IMPORTRANGE",
        "GOOGLEFINANCE",
        "CALL",
        "REGISTER",
        "REGISTER.ID",
    }
)

MAX_DEPTH = 64
MAX_RANGE_CELLS = 100_000

_TOKEN_RE = re.compile(
    r"""
      (?P<string>"(?:[^"]|"")*")
    | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
    | (?P<sheet>[A-Za-z_][A-Za-z0-9_.]*!)
    | (?P<cell>\$?[A-Za-z]{1,2}\$?[0-9]{1,3})
    | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
    | (?P<op><>|<=|>=|[-+*/^&%<>=(),:!|])
    | (?P<space>\s+)
    """,
    re.X,
)

_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,2})\$?([0-9]{1,3})$")


class FormulaError(Exception):
    """公式解析失败。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str):
        self.kind = kind
        self.value = value

    def __repr__(self):  # pragma: no cover - 调试用
        return f"<{self.kind}:{self.value}>"


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN_RE.match(source, position)
        if not match:
            raise FormulaError(ERROR_NAME)
        position = match.end()
        kind = match.lastgroup
        if kind == "space":
            continue
        tokens.append(_Token(kind, match.group()))
    return tokens


def column_index(letters: str) -> int:
    """列字母转 0 基下标。"""
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def column_letters(index: int) -> str:
    """0 基下标转列字母。"""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def parse_address(address: str) -> tuple[int, int]:
    """A1 → (行 0 基, 列 0 基)。"""
    match = _CELL_RE.match(address.replace("$", ""))
    if not match:
        raise FormulaError(ERROR_REF)
    letters, digits = match.group(1), match.group(2)
    row = int(digits) - 1
    if row < 0:
        raise FormulaError(ERROR_REF)
    return row, column_index(letters)


def format_address(row: int, column: int) -> str:
    return f"{column_letters(column)}{row + 1}"


# —— 语法树 ——


class _Node:
    __slots__ = ()


class _Literal(_Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class _Reference(_Node):
    __slots__ = ("sheet", "start", "end")

    def __init__(self, sheet: str, start: tuple, end: tuple | None):
        self.sheet = sheet
        self.start = start
        self.end = end


class _Unary(_Node):
    __slots__ = ("op", "operand")

    def __init__(self, op: str, operand: _Node):
        self.op = op
        self.operand = operand


class _Binary(_Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op: str, left: _Node, right: _Node):
        self.op = op
        self.left = left
        self.right = right


class _Percent(_Node):
    __slots__ = ("operand",)

    def __init__(self, operand: _Node):
        self.operand = operand


class _Call(_Node):
    __slots__ = ("name", "args")

    def __init__(self, name: str, args: list):
        self.name = name
        self.args = args


class _Parser:
    """递归下降解析器。"""

    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.position = 0

    def peek(self) -> _Token | None:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def next(self) -> _Token | None:
        token = self.peek()
        if token is not None:
            self.position += 1
        return token

    def expect_op(self, op: str) -> None:
        token = self.next()
        if token is None or token.kind != "op" or token.value != op:
            raise FormulaError(ERROR_NAME)

    def parse(self) -> _Node:
        node = self.comparison()
        if self.peek() is not None:
            raise FormulaError(ERROR_NAME)
        return node

    def comparison(self) -> _Node:
        node = self.concat()
        while True:
            token = self.peek()
            if (
                token is None
                or token.kind != "op"
                or token.value
                not in (
                    "=",
                    "<>",
                    "<",
                    ">",
                    "<=",
                    ">=",
                )
            ):
                return node
            self.next()
            node = _Binary(token.value, node, self.concat())

    def concat(self) -> _Node:
        node = self.additive()
        while True:
            token = self.peek()
            if token is None or token.kind != "op" or token.value != "&":
                return node
            self.next()
            node = _Binary("&", node, self.additive())

    def additive(self) -> _Node:
        node = self.multiplicative()
        while True:
            token = self.peek()
            if token is None or token.kind != "op" or token.value not in ("+", "-"):
                return node
            self.next()
            node = _Binary(token.value, node, self.multiplicative())

    def multiplicative(self) -> _Node:
        node = self.unary()
        while True:
            token = self.peek()
            if token is None or token.kind != "op" or token.value not in ("*", "/"):
                return node
            self.next()
            node = _Binary(token.value, node, self.unary())

    def unary(self) -> _Node:
        token = self.peek()
        if token is not None and token.kind == "op" and token.value in ("-", "+"):
            self.next()
            return _Unary(token.value, self.unary())
        return self.power()

    def power(self) -> _Node:
        node = self.postfix()
        token = self.peek()
        if token is not None and token.kind == "op" and token.value == "^":
            self.next()
            return _Binary("^", node, self.unary())
        return node

    def postfix(self) -> _Node:
        node = self.primary()
        while True:
            token = self.peek()
            if token is not None and token.kind == "op" and token.value == "%":
                self.next()
                node = _Percent(node)
                continue
            return node

    def primary(self) -> _Node:
        token = self.next()
        if token is None:
            raise FormulaError(ERROR_NAME)

        if token.kind == "number":
            return _Literal(_parse_number(token.value))

        if token.kind == "string":
            return _Literal(token.value[1:-1].replace('""', '"'))

        if token.kind == "sheet":
            return self._reference(token.value[:-1], token)

        if token.kind == "cell":
            return self._reference("", token)

        if token.kind == "name":
            upper = token.value.upper()
            if upper == "TRUE":
                return _Literal(True)
            if upper == "FALSE":
                return _Literal(False)
            following = self.peek()
            if (
                following is not None
                and following.kind == "op"
                and following.value == "("
            ):
                self.next()
                args = []
                if not (
                    self.peek() is not None
                    and self.peek().kind == "op"
                    and self.peek().value == ")"
                ):
                    args.append(self.comparison())
                    while True:
                        token = self.peek()
                        if token is None or token.kind != "op" or token.value != ",":
                            break
                        self.next()
                        args.append(self.comparison())
                self.expect_op(")")
                return _Call(upper, args)
            raise FormulaError(ERROR_NAME)

        if token.kind == "op" and token.value == "(":
            node = self.comparison()
            self.expect_op(")")
            return node

        raise FormulaError(ERROR_NAME)

    def _reference(self, sheet: str, token: _Token) -> _Node:
        start = parse_address(token.value)
        following = self.peek()
        if following is not None and following.kind == "op" and following.value == ":":
            self.next()
            end_token = self.next()
            if end_token is None or end_token.kind != "cell":
                raise FormulaError(ERROR_REF)
            return _Reference(sheet, start, parse_address(end_token.value))
        return _Reference(sheet, start, None)


def _parse_number(text: str):
    try:
        if re.fullmatch(r"\d+", text):
            return int(text)
        return float(text)
    except ValueError:
        raise FormulaError(ERROR_VALUE) from None


# —— 求值 ——


class _Context:
    """一次求值的上下文：工作簿 + 循环检测。"""

    def __init__(self, sheets: dict[str, dict]):
        self.sheets = sheets
        self.stack: list[str] = []
        self.cycle_members: set[str] = set()

    def sheet(self, name: str) -> dict | None:
        if not name:
            return next(iter(self.sheets.values()), None)
        for key, value in self.sheets.items():
            if key.casefold() == name.casefold():
                return value
        return None


def _is_error(value) -> bool:
    return isinstance(value, str) and value in ERROR_VALUES


def _as_number(value):
    """把值转成数字；不能转就报错。"""
    if _is_error(value):
        return value
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(Decimal(text))
        except (InvalidOperation, ValueError):
            return ERROR_VALUE
    return ERROR_VALUE


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _compare(op: str, left, right):
    if _is_error(left):
        return left
    if _is_error(right):
        return right
    if isinstance(left, str) or isinstance(right, str):
        left_text = _as_text(left).casefold()
        right_text = _as_text(right).casefold()
    else:
        left_text = _as_number(left)
        right_text = _as_number(right)
        if _is_error(left_text):
            return left_text
        if _is_error(right_text):
            return right_text
    if op == "=":
        return left_text == right_text
    if op == "<>":
        return left_text != right_text
    if op == "<":
        return left_text < right_text
    if op == ">":
        return left_text > right_text
    if op == "<=":
        return left_text <= right_text
    return left_text >= right_text


def _eval_node(node: _Node, ctx: _Context):
    if isinstance(node, _Literal):
        return node.value

    if isinstance(node, _Reference):
        return _eval_reference(node, ctx)

    if isinstance(node, _Percent):
        value = _as_number(_eval_node(node.operand, ctx))
        if _is_error(value):
            return value
        return value / 100.0

    if isinstance(node, _Unary):
        value = _as_number(_eval_node(node.operand, ctx))
        if _is_error(value):
            return value
        return -value if node.op == "-" else value

    if isinstance(node, _Binary):
        return _eval_binary(node, ctx)

    if isinstance(node, _Call):
        return _eval_call(node, ctx)

    return ERROR_VALUE


def _eval_reference(node: _Reference, ctx: _Context):
    sheet = ctx.sheet(node.sheet)
    if sheet is None:
        return ERROR_REF
    if node.end is None:
        return _cell_value(sheet, node.start, ctx)
    values = _range_values(sheet, node.start, node.end, ctx)
    return values


def _range_values(sheet: dict, start, end, ctx) -> list:
    row_low, row_high = sorted((start[0], end[0]))
    col_low, col_high = sorted((start[1], end[1]))
    count = (row_high - row_low + 1) * (col_high - col_low + 1)
    if count > MAX_RANGE_CELLS:
        raise FormulaError(ERROR_NUM)
    values = []
    for row in range(row_low, row_high + 1):
        for column in range(col_low, col_high + 1):
            values.append(_cell_value(sheet, (row, column), ctx))
    return values


def _cell_value(sheet: dict, position: tuple, ctx: _Context):
    """取一个单元格的值。公式会递归求值，循环则记入 cycle_members。"""
    row, column = position
    address = format_address(row, column)
    source = (sheet.get("cells") or {}).get(address)
    if source is None:
        return None
    if not isinstance(source, str):
        return source
    text = source.strip()
    if not text.startswith("="):
        return _literal_value(text)
    if address in ctx.stack:
        # 循环：把环上的成员都标记出来
        index = ctx.stack.index(address)
        for member in ctx.stack[index:]:
            ctx.cycle_members.add(member)
        return ERROR_CIRC
    if len(ctx.stack) >= MAX_DEPTH:
        return ERROR_NUM
    ctx.stack.append(address)
    try:
        return _evaluate_formula(text[1:], ctx)
    except FormulaError as exc:
        return exc.code
    finally:
        ctx.stack.pop()


def _literal_value(text: str):
    """字面量：空 → 空；TRUE/FALSE → 布尔；数字 → 数字；否则文本。"""
    if text == "":
        return None
    upper = text.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if upper in ERROR_VALUES:
        return upper
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        try:
            return int(text) if re.fullmatch(r"[+-]?\d+", text) else float(text)
        except ValueError:
            return ERROR_VALUE
    return text


def _evaluate_formula(source: str, ctx: _Context):
    tokens = _tokenize(source)
    if not tokens:
        return ERROR_NAME
    node = _Parser(tokens).parse()
    return _eval_node(node, ctx)


def _eval_binary(node: _Binary, ctx: _Context):
    op = node.op

    if op in ("=", "<>", "<", ">", "<=", ">="):
        return _compare(op, _eval_node(node.left, ctx), _eval_node(node.right, ctx))

    if op == "&":
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.right, ctx)
        if _is_error(left):
            return left
        if _is_error(right):
            return right
        return _as_text(left) + _as_text(right)

    left = _as_number(_eval_node(node.left, ctx))
    if _is_error(left):
        return left
    right = _as_number(_eval_node(node.right, ctx))
    if _is_error(right):
        return right

    try:
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                return ERROR_DIV0
            return left / right
        if op == "^":
            if left < 0 and not float(right).is_integer():
                return ERROR_NUM
            try:
                return float(left) ** float(right)
            except (OverflowError, ValueError):
                return ERROR_NUM
    except (OverflowError, ZeroDivisionError):
        return ERROR_NUM
    return ERROR_VALUE


def _numeric_aggregate(name: str, values: list):
    """数值聚合。

    引用到的格子里有错误值时，**错误必须传上来**——把错误跳过去会让
    「少了一个坏格子」的求和看起来像一个正常结果。
    """
    numbers = []
    for value in values:
        if _is_error(value):
            return value
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            numbers.append(1.0 if value else 0.0)
            continue
        number = _as_number(value)
        if _is_error(number):
            return number
        numbers.append(number)
    if not numbers:
        if name == "COUNT":
            return 0.0
        return ERROR_DIV0
    if name == "SUM":
        return sum(numbers)
    if name == "AVERAGE":
        return sum(numbers) / len(numbers)
    if name == "MIN":
        return min(numbers)
    if name == "MAX":
        return max(numbers)
    if name == "MEDIAN":
        ordered = sorted(numbers)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2
    return ERROR_VALUE


def _flatten(node_value) -> list:
    if isinstance(node_value, list):
        result = []
        for item in node_value:
            result.extend(_flatten(item))
        return result
    return [node_value]


def _eval_call(node: _Call, ctx: _Context):
    name = node.name
    if name in DISALLOWED_FUNCTIONS:
        # 易变与外部调用：不可复现，直接拒绝
        return ERROR_NAME
    if name == "IFERROR":
        if len(node.args) != 2:
            return ERROR_VALUE
        value = _eval_node(node.args[0], ctx)
        if _is_error(value):
            return _eval_node(node.args[1], ctx)
        return value
    if name == "IF":
        if len(node.args) != 3:
            return ERROR_VALUE
        condition = _eval_node(node.args[0], ctx)
        if _is_error(condition):
            return condition
        truthy = (
            bool(_as_number(condition))
            if not isinstance(condition, str)
            else bool(condition)
        )
        return _eval_node(node.args[1] if truthy else node.args[2], ctx)
    if name == "AND" or name == "OR":
        result = name == "AND"
        for argument in node.args:
            value = _eval_node(argument, ctx)
            if _is_error(value):
                return value
            truthy = (
                bool(_as_number(value)) if not isinstance(value, str) else bool(value)
            )
            result = (result and truthy) if name == "AND" else (result or truthy)
        return result
    if name == "NOT":
        if len(node.args) != 1:
            return ERROR_VALUE
        value = _eval_node(node.args[0], ctx)
        if _is_error(value):
            return value
        return not (
            bool(_as_number(value)) if not isinstance(value, str) else bool(value)
        )

    values = [_eval_node(argument, ctx) for argument in node.args]

    if name in ("SUM", "AVERAGE", "MIN", "MAX", "MEDIAN"):
        return _numeric_aggregate(name, _flatten(values))
    if name == "COUNT":
        return float(
            sum(1 for value in _flatten(values) if value is not None and value != "")
        )
    if name == "COUNTA":
        return float(
            sum(1 for value in _flatten(values) if value is not None and value != "")
        )
    if name == "ROUND":
        if len(values) != 2:
            return ERROR_VALUE
        digits = _as_number(values[1])
        if _is_error(digits):
            return digits
        number = _as_number(values[0])
        if _is_error(number):
            return number
        return round(number, int(digits))
    if name == "ABS":
        if len(values) != 1:
            return ERROR_VALUE
        number = _as_number(values[0])
        return number if _is_error(number) else abs(number)
    if name == "SQRT":
        if len(values) != 1:
            return ERROR_VALUE
        number = _as_number(values[0])
        if _is_error(number):
            return number
        if number < 0:
            return ERROR_NUM
        return math.sqrt(number)
    if name == "POWER":
        if len(values) != 2:
            return ERROR_VALUE
        base = _as_number(values[0])
        exponent = _as_number(values[1])
        if _is_error(base):
            return base
        if _is_error(exponent):
            return exponent
        if base < 0 and not float(exponent).is_integer():
            return ERROR_NUM
        try:
            return float(base) ** float(exponent)
        except (OverflowError, ValueError):
            return ERROR_NUM
    if name == "LEN":
        if len(values) != 1:
            return ERROR_VALUE
        return float(len(_as_text(values[0])))
    if name == "CONCAT":
        parts = []
        for value in _flatten(values):
            if _is_error(value):
                return value
            parts.append(_as_text(value))
        return "".join(parts)
    if name == "ISNUMBER":
        if len(values) != 1:
            return ERROR_VALUE
        value = values[0]
        if _is_error(value):
            return False
        return not isinstance(value, str)
    return ERROR_NAME


def evaluate_sheets(sheets: dict[str, dict]) -> dict[str, dict]:
    """算出一个工作簿里所有表的所有格子。

    返回 {表名: {地址: 值}}。值可能是数字、文本、布尔、空，或错误值。
    """
    ctx = _Context(sheets)
    result: dict[str, dict] = {}
    for name, sheet in sheets.items():
        values: dict[str, object] = {}
        rows = int(sheet.get("rows") or 0)
        columns = int(sheet.get("columns") or 0)
        for row in range(rows):
            for column in range(columns):
                address = format_address(row, column)
                if address not in (sheet.get("cells") or {}):
                    continue
                values[address] = _cell_value(sheet, (row, column), ctx)
        result[name] = values
    return result


def evaluate_sheet(sheet: dict, name: str = "Sheet1") -> dict:
    """算一张表。"""
    return evaluate_sheets({name: sheet})[name]


def format_value(value) -> str:
    """把值渲染成显示文本。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(round(value, 10))
    return str(value)
