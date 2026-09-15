// Read dcf_inputs.txt from ticker.py and calculate a simple perpetual-growth DCF.
// Build: g++ -std=c++17 -O2 APE.cpp -o APE.exe
// Run:   .\APE.exe dcf_inputs.txt

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>

struct DcfInputs
{
    std::string ticker;
    std::string currency = "USD";
    double price = 0.0;
    double fcfYearT = 0.0;
    double fcfFinalYear = 0.0;
    int forecastYears = 0;
    double fcfForecastGrowthRate = 0.0;
    double discountRate = 0.0;
    double terminalGrowthRate = 0.0;
    double sharesOutstanding = 0.0;
    double cash = 0.0;
    double debt = 0.0;
};

std::string trim(const std::string &text)
{
    const std::string whitespace = " \t\r\n";
    const auto begin = text.find_first_not_of(whitespace);
    if (begin == std::string::npos)
        return "";
    const auto end = text.find_last_not_of(whitespace);
    return text.substr(begin, end - begin + 1);
}

bool readDcfInputs(const std::string &filename, DcfInputs &input, std::string &error)
{
    std::ifstream file(filename);
    if (!file)
    {
        error = "Could not open " + filename + ". Run ticker.py first.";
        return false;
    }

    std::map<std::string, std::string> values;
    std::string line;
    while (std::getline(file, line))
    {
        line = trim(line);
        if (line.empty() || line[0] == '#')
            continue;
        const auto separator = line.find('=');
        if (separator == std::string::npos)
            continue;
        values[trim(line.substr(0, separator))] = trim(line.substr(separator + 1));
    }

    auto number = [&values, &error](const std::string &key, double &destination)
    {
        const auto found = values.find(key);
        if (found == values.end() || found->second.empty())
        {
            error = "Missing required input: " + key;
            return false;
        }
        try
        {
            destination = std::stod(found->second);
            if (!std::isfinite(destination))
                throw std::invalid_argument("not finite");
            return true;
        }
        catch (const std::exception &)
        {
            error = "Invalid numeric input for " + key + ": " + found->second;
            return false;
        }
    };

    double forecastYearsRaw = 0.0;
    if (values.count("ticker"))
        input.ticker = values["ticker"];
    if (values.count("currency"))
        input.currency = values["currency"];
    if (!number("fcf_year_t", input.fcfYearT) ||
        !number("fcf_final_year", input.fcfFinalYear) ||
        !number("forecast_years", forecastYearsRaw) ||
        !number("fcf_forecast_growth_rate", input.fcfForecastGrowthRate) ||
        !number("discount_rate", input.discountRate) ||
        !number("terminal_growth_rate", input.terminalGrowthRate) ||
        !number("shares_outstanding", input.sharesOutstanding) ||
        !number("cash", input.cash) ||
        !number("debt", input.debt))
    {
        return false;
    }
    input.forecastYears = static_cast<int>(forecastYearsRaw);
    if (input.forecastYears <= 0 || forecastYearsRaw != input.forecastYears)
    {
        error = "forecast_years must be a positive whole number.";
        return false;
    }
    if (values.count("price") && !values["price"].empty())
    {
        try
        {
            input.price = std::stod(values["price"]);
        }
        catch (const std::exception &)
        {
            input.price = 0.0;
        }
    }
    return true;
}

int main(int argc, char *argv[])
{
    const std::string filename = argc > 1 ? argv[1] : "dcf_inputs.txt";
    DcfInputs input;
    std::string error;
    if (!readDcfInputs(filename, input, error))
    {
        std::cerr << "Input error: " << error << '\n';
        return 1;
    }
    if (input.discountRate <= input.terminalGrowthRate)
    {
        std::cerr << "Input error: discount_rate must be greater than terminal_growth_rate.\n";
        return 1;
    }
    if (input.sharesOutstanding <= 0.0)
    {
        std::cerr << "Input error: shares_outstanding must be positive.\n";
        return 1;
    }

    // Forecast FCFF from year 1 through the terminal year.
    double presentValueForecastFcf = 0.0;
    for (int year = 1; year <= input.forecastYears; ++year)
    {
        const double forecastFcf = input.fcfYearT * std::pow(1.0 + input.fcfForecastGrowthRate, year);
        presentValueForecastFcf += forecastFcf / std::pow(1.0 + input.discountRate, year);
    }

    const double terminalValue = input.fcfFinalYear * (1.0 + input.terminalGrowthRate) /
                                 (input.discountRate - input.terminalGrowthRate);
    const double presentValueTerminalValue = terminalValue /
                                             std::pow(1.0 + input.discountRate, input.forecastYears);
    const double enterpriseValue = presentValueForecastFcf + presentValueTerminalValue;
    const double equityValue = enterpriseValue + input.cash - input.debt;
    const double impliedValuePerShare = equityValue / input.sharesOutstanding;

    std::cout << std::fixed << std::setprecision(2);
    std::cout << "=== " << input.ticker << " DCF ===\n";
    std::cout << "PV of forecast FCF:       " << input.currency << " " << presentValueForecastFcf << '\n';
    std::cout << "PV of terminal value:     " << input.currency << " " << presentValueTerminalValue << '\n';
    std::cout << "Enterprise value:          " << input.currency << " " << enterpriseValue << '\n';
    std::cout << "Equity value:              " << input.currency << " " << equityValue << '\n';
    std::cout << "Implied value per share:   " << input.currency << " " << impliedValuePerShare << '\n';
    if (input.price > 0.0)
    {
        const double upside = impliedValuePerShare / input.price - 1.0;
        std::cout << "Latest market price:       " << input.currency << " " << input.price << '\n';
        std::cout << "Implied upside/(downside): " << upside * 100.0 << "%\n";
    }
    return 0;
}
