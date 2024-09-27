from xgboost import XGBRegressor
import numpy as np
import shap
import xgboost as xgb
import os

class CustomXGBoost():

    def __init__(self, base_params):
        """
        Initialize the CustomXGBoost class.
        
        Parameters:
        params (dict): Parameters to be passed to the XGBRegressor model.
        """
        self.base_params = base_params

    def fit(self, train_X, train_Y, valid_X, valid_Y, fix_seed=False):

        dtrain = xgb.DMatrix(train_X, train_Y)
        dval = xgb.DMatrix(valid_X, valid_Y)

        train_params = {k: v for k, v in self.base_params.items() if k not in ['n_estimators', 'early_stopping_rounds']} #used to get rid of the warnings when training the model
        self.model = xgb.train(train_params, dtrain, evals=[(dval, 'eval')], num_boost_round=self.base_params['n_estimators'], early_stopping_rounds=self.base_params['early_stopping_rounds'], verbose_eval=False)

    def predict(self, test_X, return_shaps=False):
        
        dtest = xgb.DMatrix(test_X)
        out = {}
        out['predictions'] = self.model.predict(dtest)
        
        if return_shaps:
            explainer = shap.TreeExplainer(self.model)
            shaps = explainer(test_X.values)
            return {**out, **{'shap_values':shaps}}
        
        return out
    
    def get_important_features(self):
        return self.model.get_score(importance_type='gain')


class EnsembleXGBoost():
    def __init__(self, base_params=None):
        """
        Initialize the EnsembleXGBoost class.
        
        Parameters:
        base_params (dict): Parameters to be passed to each XGBRegressor model.
        """
        self.models = []
        self.base_params = base_params

    def fit(self, data_subset,fix_seed=False):
        """
        Fit multiple XGBRegressor models based on the training-validation splits.
        
        Parameters:
        data_subset (list): List of tuples containing training, validation and test data.
        """
        for idx,data in enumerate(data_subset):
            
            dtrain = xgb.DMatrix(data['train_X'], data['train_Y'])
            dval = xgb.DMatrix(data['valid_X'], data['valid_Y'])

            if fix_seed:
                self.base_params['seed'] = idx

            train_params = {k: v for k, v in self.base_params.items() if k not in ['n_estimators', 'early_stopping_rounds']} #used to get rid of the warnings when training the model
            booster = xgb.train(train_params, dtrain, evals=[(dval, 'eval')], 
                                num_boost_round=self.base_params['n_estimators'], 
                                early_stopping_rounds=self.base_params['early_stopping_rounds'], 
                                verbose_eval=False)
                
            self.models.append(booster)

            #model = XGBRegressor(**self.base_params)
            #model.fit(X_train.values, y_train, eval_set=[(X_valid.values, y_valid)], verbose=False)
            #self.models.append(model)
            

    def predict(self,test_X,return_shaps=False,return_stds=False):
        """
        Make predictions based on the ensemble of models and average them.
        
        Parameters:
        X_test (DataFrame): Test features.
        
        Returns:
        np.array: Averaged predictions.
        """
        preds = []
        shaps = []
        
        for model in self.models:
            #check whethere test_X has the same features as the model
            try:
                test_X = test_X[model.feature_names]
            except:
                raise ValueError(f'Test data has different features than the model. Check the feature names.')

            dtest = xgb.DMatrix(test_X)
            preds.append(model.predict(dtest))
            
            if return_shaps:
                explainer = shap.TreeExplainer(model)
                #shaps.append(explainer.shap_values(X_test.values))
                shaps.append(explainer(test_X.values))
                
        if return_shaps:
            #obtain a tridimensional array with the shap values
            shap_values = np.array([x.values for x in shaps])
            shap_values = np.mean(shap_values,axis=0)
            shap_base_values = np.array([x.base_values for x in shaps])
            shap_base_values = np.mean(shap_base_values,axis=0)
            #obtain the mean of the shap values
            
            #if inverse_map:
            #    feature_names = [inverse_map[x] for x in X_test.columns]
            #else:   
            feature_names = test_X.columns
           
            explanation = shap.Explanation(values=shap_values,
                                base_values=shap_base_values,
                                data=test_X.values,
                                feature_names=feature_names,
                                instance_names=list(test_X.index))
            
            #return np.mean(preds, axis=0),explanation

            #output = {}
            #output['predictions'] = np.mean(preds, axis=0)  
            #output['shap_values'] = explanation

            #return output
        
        output = {}
        output['predictions'] = np.mean(preds, axis=0)

        if return_shaps:
            output['shap_values'] = explanation

        if return_stds:
            output['std'] = np.std(preds, axis=0)
        
        return output
    
    def get_important_features(self):
        return np.mean([model.feature_importances_ for model in self.models], axis=0)
    

    def save_model(self, path):
        for i,model in enumerate(self.models):
            model.save_model(f'{path}/{i}.json')

    @classmethod
    def load_model(cls, path):
        instance = cls(None)
        instance.models = []
        i = 0
        while True:
            model_path = f'{path}/{i}.json'
            if not os.path.exists(model_path):
                break
                #raise ValueError(f'Model {model_path} does not exist')
            model = xgb.Booster()
            model.load_model(model_path)
            instance.models.append(model)
            i += 1

        if len(instance.models) == 0:
            raise ValueError(f'No models found in {path}')
        
        return instance