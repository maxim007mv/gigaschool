/**
 * Компактные SVG-иконки для бейджей и степпера.
 * Без emoji/символов-«стикеров» — одинаковый размер и цвет через currentColor.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { title?: string };

function base(props: IconProps) {
  const { title, className, ...rest } = props;
  return {
    className,
    rest,
    title,
    shared: {
      width: 12,
      height: 12,
      viewBox: "0 0 16 16",
      fill: "none",
      "aria-hidden": title ? undefined : (true as const),
      role: title ? ("img" as const) : undefined,
      focusable: false as const,
    },
  };
}

export function IconCheck(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <path
        d="M3.5 8.5 6.5 11.5 12.5 4.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function IconCross(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <path
        d="M4 4 12 12M12 4 4 12"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function IconAlert(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <path
        d="M8 3.2 13.5 13H2.5L8 3.2Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M8 7v2.8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="8" cy="11.4" r="0.8" fill="currentColor" />
    </svg>
  );
}

export function IconInfo(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8 7.2V11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="8" cy="5.2" r="0.85" fill="currentColor" />
    </svg>
  );
}

export function IconDot(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <circle cx="8" cy="8" r="2.4" fill="currentColor" />
    </svg>
  );
}

export function IconChevronRight(props: IconProps) {
  const { className, rest, title, shared } = base(props);
  return (
    <svg {...shared} className={className} {...rest}>
      {title ? <title>{title}</title> : null}
      <path
        d="M6 3.5 11 8 6 12.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
