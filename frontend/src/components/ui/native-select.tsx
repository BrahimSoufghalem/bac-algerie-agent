import * as React from "react";
import { cn } from "../../lib/utils";
// Native form semantics are retained for required fields, FormData and keyboard use.
export const NativeSelect = React.forwardRef<
  HTMLSelectElement,
  React.ComponentProps<"select">
>(({ className, children, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "min-h-11 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
      className,
    )}
    {...props}
  >
    {children}
  </select>
));
NativeSelect.displayName = "NativeSelect";
