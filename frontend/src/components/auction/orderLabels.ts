import type { OrderState } from "@/lib/api";
import type { Tone } from "@/components/ui";

export const ORDER_LABEL: Record<OrderState, { label: string; tone: Tone }> = {
  INVOICED: { label: "Awaiting payment", tone: "info" },
  AUTHORIZED: { label: "Payment authorised", tone: "info" },
  AWAITING_CAPTURE_RETRY: { label: "Capturing payment", tone: "info" },
  CAPTURED: { label: "Captured", tone: "positive" },
  IN_ESCROW: { label: "Held in escrow", tone: "positive" },
  SHIPPED: { label: "Shipped", tone: "positive" },
  DISPUTED: { label: "Disputed", tone: "danger" },
  RELEASED: { label: "Released to seller", tone: "positive" },
  REFUNDED: { label: "Refunded", tone: "neutral" },
  CANCELLED: { label: "Cancelled", tone: "danger" },
};
