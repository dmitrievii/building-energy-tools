export const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

export const REFERENCE_LAYERS = [
  {id:'ref.innenputz', name:'Innenputz', thickness_m:0.015, lambda_W_mK:0.7, mu:10, category:'gypsum_and_plaster'},
  {id:'ref.mineralwolle', name:'Mineralwolle', thickness_m:0.16, lambda_W_mK:0.038, mu:1.4, category:'batt_insulation'},
  {id:'ref.mauerwerk', name:'Mauerwerk', thickness_m:0.25, lambda_W_mK:0.35, mu:8, category:'masonry'},
  {id:'ref.aussenputz', name:'Außenputz', thickness_m:0.01, lambda_W_mK:1.0, mu:10, category:'mortars_and_renders'},
];

// Reference climate transcribed from the supplied Glaser_AT.xlsx workbook.
// These values are a workbook regression dataset, not yet a normative climate catalogue.
export const KLAGENFURT_REFERENCE_MONTHLY = [
  [-2.63,0.87,22.00,0.4858224346,31],
  [ 0.17,0.79,22.00,0.5068728631,28],
  [ 4.89,0.72,22.00,0.4936386278,31],
  [ 9.74,0.71,22.00,0.5158005107,30],
  [14.14,0.70,24.07,0.4948141326,31],
  [17.89,0.69,25.95,0.4874876052,30],
  [19.80,0.74,26.90,0.5252668151,31],
  [18.98,0.72,26.49,0.5091811655,31],
  [15.36,0.80,24.68,0.5509584994,30],
  [ 9.72,0.86,22.00,0.5869833017,31],
  [ 3.43,0.87,22.00,0.5375006155,30],
  [-1.38,0.90,22.00,0.5110586674,31],
].map(([te_C,rhe,ti_C,rhi,days], i) => ({month:i+1, te_C,rhe,ti_C,rhi,days}));
