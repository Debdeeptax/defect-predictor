package demo.orders;

import java.util.ArrayList;
import java.util.List;

/** Order service (sample Java file — partial metrics via lizard). */
public class OrderService {
    private final List<String> audit = new ArrayList<>();

    public double checkout(double total, String region, boolean express) {
        double shipping = 0;
        if (total < 50) {
            shipping = express ? 15 : 7.5; // small orders pay shipping
        } else if (express) {
            shipping = 5;
        }
        switch (region) {
            case "EU": total *= 1.2; break;
            case "US": total *= 1.07; break;
            default: break;
        }
        audit.add("checkout:" + total);
        return total + shipping;
    }

    public int countAudits() {
        return audit.size();
    }
}
