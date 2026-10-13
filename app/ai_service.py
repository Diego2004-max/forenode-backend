import numpy as np
from sklearn.linear_model import LinearRegression

class AgriculturalAIModel:
    def __init__(self):
        # Modelo entrenado con estacionalidad, temperatura y precipitación
        self.model = LinearRegression()
        # Datos sintéticos base para entrenamiento inicial del motor Scikit-Learn
        X_train = np.array([
            [1, 15.5, 40.0], [3, 18.2, 20.5], [6, 21.0, 10.0], 
            [9, 14.0, 75.0], [12, 13.5, 60.0], [4, 16.8, 30.0]
        ])
        y_train = np.array([1250.0, 1400.0, 1100.0, 1850.0, 1920.0, 1350.0])
        self.model.fit(X_train, y_train)

    def predict_demand(self, month: int, temp: float, rain: float) -> float:
        features = np.array([[month, temp, rain]])
        prediction = self.model.predict(features)
        return float(max(200.0, prediction[0]))

ai_model_instance = AgriculturalAIModel()