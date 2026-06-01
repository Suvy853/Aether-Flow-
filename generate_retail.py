import pandas as pd
import numpy as np
import os

os.makedirs('examples', exist_ok=True)
np.random.seed(42)
n = 10000

countries = ['UnitedKingdom','Germany','France','Netherlands','Australia','Spain','Belgium']
categories = ['Electronics','Clothing','HomeGarden','Sports','Books','Toys','Food']
descriptions = ['PremiumWidgetA','ClassicWidgetB','DeluxeWidgetC','StandardWidgetD','BudgetWidgetE','ProWidgetF','EliteWidgetG','BasicWidgetH']

df = pd.DataFrame({
    'InvoiceNo': [f'INV{str(i).zfill(6)}' for i in range(n)],
    'StockCode': np.random.choice([f'SKU{i:04d}' for i in range(500)], n),
    'Description': np.random.choice(descriptions, n),
    'Quantity': np.random.randint(1, 100, n),
    'InvoiceDate': pd.date_range('2010-12-01', periods=n, freq='1h').strftime('%Y-%m-%d'),
    'UnitPrice': np.round(np.random.uniform(0.5, 150.0, n), 2),
    'CustomerID': np.random.randint(10000, 20000, n),
    'Country': np.random.choice(countries, n),
    'Category': np.random.choice(categories, n),
    'TotalRevenue': np.round(np.random.uniform(1.0, 5000.0, n), 2),
})

df.to_csv('examples/retail.csv', index=False)
print(f'Done: {len(df)} rows')
print(df.head(3))