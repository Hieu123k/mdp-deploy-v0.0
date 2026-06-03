/** Nối className có điều kiện (gọn, không cần dependency). */
export type ClassValue = string | false | null | undefined;

export function cn(...classes: ClassValue[]): string {
  return classes.filter(Boolean).join(" ");
}
