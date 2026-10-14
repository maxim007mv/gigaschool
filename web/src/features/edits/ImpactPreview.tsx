/**
 * ImpactPreview — «что изменится» до применения правки (Д3 §4.5, US-7).
 *
 * Показывает список пересобираемых элементов и то, что останется прежним
 * (часы, компетенции), — чтобы правка была без страха сломать каркас.
 */

import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { cx } from "../../shared/ui/cx";

export interface ImpactPreviewProps {
  affected: string[];
  unchanged: string[];
  className?: string;
}

export function ImpactPreview({ affected, unchanged, className }: ImpactPreviewProps) {
  return (
    <div className={cx("flex flex-col gap-md", className)}>
      <section aria-label={T.kit.affected}>
        <h3 className="mb-sm text-base font-semibold text-ink">
          {T.kit.affected}: {affected.length}
        </h3>
        <ul className="flex flex-wrap gap-xs">
          {affected.map((ref) => (
            <li key={ref}>
              <Badge variant="info" className="tnum">
                {ref}
              </Badge>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label={T.kit.unchanged}>
        <h3 className="mb-sm text-base font-semibold text-ink">{T.kit.unchanged}</h3>
        <ul className="flex flex-wrap gap-xs">
          {unchanged.map((item) => (
            <li key={item}>
              <Badge variant="neutral">{item}</Badge>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
