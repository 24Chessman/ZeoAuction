import { formatMoney, parseMoney, parseMoneyInput, toMoneyString } from "./money";

describe("money", () => {
  it("parses wire amounts into integer cents", () => {
    expect(parseMoney("1250.00")).toBe(125_000);
    expect(parseMoney("0.05")).toBe(5);
    expect(parseMoney("10.10")).toBe(1_010);
  });

  it("refuses anything that is not a two-decimal string", () => {
    for (const bad of ["1250", "1250.0", "1,250.00", "-1.00", "01.00", "1e3", ""]) {
      expect(() => parseMoney(bad)).toThrow();
    }
  });

  it("formats cents back to the wire format", () => {
    expect(toMoneyString(125_000)).toBe("1250.00");
    expect(toMoneyString(5)).toBe("0.05");
    expect(toMoneyString(0)).toBe("0.00");
    expect(() => toMoneyString(1.5)).toThrow();
    expect(() => toMoneyString(-1)).toThrow();
  });

  it("round-trips without floating point drift", () => {
    for (const cents of [1, 10, 99, 100, 101, 999_999, 1_234_567_89]) {
      expect(parseMoney(toMoneyString(cents))).toBe(cents);
    }
  });

  it("reads what people type", () => {
    expect(parseMoneyInput("1,250")).toBe(125_000);
    expect(parseMoneyInput(" 12.5 ")).toBe(1_250);
    expect(parseMoneyInput("12.")).toBe(1_200);
    expect(parseMoneyInput("0.07")).toBe(7);
    expect(parseMoneyInput("12.345")).toBeNull();
    expect(parseMoneyInput("abc")).toBeNull();
    expect(parseMoneyInput("")).toBeNull();
  });

  it("formats for display in the API's currency", () => {
    expect(formatMoney(125_000, "USD")).toBe("$1,250.00");
    expect(formatMoney(125_000, "USD", { compact: true })).toBe("$1,250");
    expect(formatMoney(5_000, "INR")).toContain("50.00");
  });
});
