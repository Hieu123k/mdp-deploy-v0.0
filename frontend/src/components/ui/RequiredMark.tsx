/**
 * Prompt 47 (O): a single shared red "*" required-field indicator. Purely visual - it never changes
 * validation, payload, or submit behaviour. Used by the `requiredMark` prop on Input/Select and
 * inline next to any custom <label> for a required field.
 *
 * The "*" is decorative (aria-hidden) so screen readers don't read a bare asterisk; title="Required"
 * gives a hover tooltip for sighted users.
 */
export function RequiredMark() {
  return (
    <span className="text-danger" aria-hidden="true" title="Required">
      {" *"}
    </span>
  );
}
