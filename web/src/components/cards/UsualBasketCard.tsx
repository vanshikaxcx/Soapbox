import { useUsualBasket } from "../../state/useUsualBasket";

export interface UsualBasketCardProps {
  /** The most recent shopper turn's text, or null before anything's been said yet. */
  lastShopperText: string | null;
  /** Loading always resubmits through the canonical path - a fresh search, never a cached result. */
  onLoad: (text: string) => void;
  disabled?: boolean;
}

export function UsualBasketCard({ lastShopperText, onLoad, disabled = false }: UsualBasketCardProps) {
  const { saved, savedRelativeTime, isStale, save } = useUsualBasket();

  return (
    <div className="pp-card pp-usual-basket">
      <h3>Usual basket</h3>
      {lastShopperText !== null && (
        <button
          type="button"
          className="pp-button pp-button--secondary"
          onClick={() => save(lastShopperText)}
          disabled={disabled}
        >
          Save this as my usual
        </button>
      )}
      {saved !== null && (
        <div className="pp-usual-basket__saved">
          <p>
            Saved <span className="pp-usual-basket__age">{savedRelativeTime}</span>:
            &ldquo;{saved.text}&rdquo;
          </p>
          {isStale && (
            <p className="pp-usual-basket__stale">
              That was saved a while ago — loading it runs a fresh search, never old prices.
            </p>
          )}
          <button
            type="button"
            className="pp-button pp-button--primary"
            onClick={() => onLoad(saved.text)}
            disabled={disabled}
          >
            Load usual
          </button>
        </div>
      )}
    </div>
  );
}
