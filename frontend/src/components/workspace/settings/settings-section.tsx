import { cn } from "@/lib/utils";

/** 提供设置页通用分区结构，统一标题、说明与内容的语义层级。 */
export function SettingsSection({
  className,
  title,
  description,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn(className)}>
      <header className="space-y-2">
        <div className="text-lg font-semibold">{title}</div>
        {description && (
          <div className="text-muted-foreground text-sm">{description}</div>
        )}
      </header>
      <main className="mt-4">{children}</main>
    </section>
  );
}
