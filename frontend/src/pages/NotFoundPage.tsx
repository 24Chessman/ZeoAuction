import { Compass } from "lucide-react";
import { ButtonLink, EmptyState } from "@/components/ui";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-page px-4 py-20 sm:px-6">
      <EmptyState icon={<Compass className="size-5" />} title="Page not found" action={<ButtonLink to="/auctions">Browse auctions</ButtonLink>}>
        The page you're looking for doesn't exist or has moved.
      </EmptyState>
    </div>
  );
}
